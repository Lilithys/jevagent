"""Replay a recorded flow.

Before each checked step: wait for the step's anchor to be visible and stable,
then perform the recorded gesture shifted by wherever the anchor was found.
If it does not show up in time, stop without touching anything else. After the
last step, compare the screen with the one you ended the recording on.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from jevagent.errors import DeviceError, Interrupted
from jevagent.flow import MATCH_THRESHOLD, RETRY_TAPS, RETRY_WAIT, Flow, Step
from jevagent.recorder import save_jpeg
from jevagent.vision import (
    ANCHOR_SIDE,
    SAME_SCREEN,
    Anchor,
    Match,
    find_anchor,
    make_anchor,
    screen_similarity,
    to_work,
)

STATUS = {"success": "成功", "failed": "失败", "stopped": "已停止", "error": "出错", "running": "未完成"}
POLL = 0.05  # pause between frames while waiting (a frame itself takes ~0.1 s)
STABLE = 3  # work pixels the anchor may move between the frames that confirm it
CONFIRM = 2  # consecutive matching frames needed
CONFIRM_LONG = 3  # ...after LONG_WAIT: long waits over busy scenes (battles) invite look-alikes
LONG_WAIT = 20.0
SKIP_SETTLE = 3.0  # an optional step is skipped once the next step's screen has stayed this long
REACT_SETTLE = 2.0  # after a react step fires, let the screen change (recorded cutscene taps: 1.3-3 s apart)
REACT_MAX = 15  # react firings per block before giving up
NUDGE_AFTER = 6.0  # react block: seconds with nothing recognisable before a nudge tap
NUDGE_MAX = 3


@dataclass
class StepResult:
    step: int  # 1-based
    status: str  # done | failed
    score: float | None = None  # anchor match, or start-screen similarity for an unchecked first step
    waited: float = 0.0  # seconds from the end of the previous step until this gesture started
    shift: list[float] = field(default_factory=lambda: [0.0, 0.0])
    taps: int = 0  # gestures actually sent (until_next steps may tap more than once)
    error: str = ""


@dataclass
class RunResult:
    flow: str
    revision: int
    started: str
    status: str = "running"  # success | failed | stopped | error
    reason: str = ""
    steps: list[StepResult] = field(default_factory=list)
    end_score: float | None = None
    image: str | None = None  # last frame seen, saved in the run folder
    shots: list[str] = field(default_factory=list)  # screens a react step responded to (e.g. a gold card)
    seconds: float = 0.0


def new_run_dir(flow_dir: Path) -> Path:
    base = flow_dir / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    path, n = base, 1
    while path.exists():
        n += 1
        path = base.with_name(f"{base.name}-{n}")
    return path


def load_runs(flow_dir: Path) -> list[tuple[Path, dict]]:
    runs = []
    for path in sorted((flow_dir / "runs").glob("*/run.json")):
        try:
            runs.append((path.parent, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return runs


class Player:
    def __init__(
        self,
        device,
        flow: Flow,
        folder: Path,
        *,
        log: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
        stop: threading.Event | None = None,
        start: int = 1,
    ) -> None:
        self.device, self.flow, self.folder, self.log, self.clock = device, flow, folder, log, clock
        self.start = start  # 1-based step to begin with (resume after doing the earlier steps by hand)
        self.stop = stop or threading.Event()
        self._sleep_impl = sleep
        self._images: dict[str, np.ndarray] = {}
        self.last_frame: np.ndarray | None = None

    def _sleep(self, seconds: float) -> None:
        if self._sleep_impl is not None:
            self._sleep_impl(seconds)
            if self.stop.is_set():
                raise Interrupted("已停止")
        elif self.stop.wait(max(seconds, 0)):
            raise Interrupted("已停止")

    def _image(self, name: str) -> np.ndarray:
        if name not in self._images:
            image = cv2.imread(str(self.folder / name), cv2.IMREAD_COLOR)
            if image is None:
                raise DeviceError(f"流程文件缺失或损坏: {self.folder / name}")
            self._images[name] = image
        return self._images[name]

    def _frame(self) -> np.ndarray:
        self.last_frame = self.device.frame()
        return self.last_frame

    def _wait_anchor(
        self,
        anchor: Anchor,
        threshold: float,
        timeout: float,
        skip: Callable[[np.ndarray], bool] | None = None,
    ) -> tuple[Match | None, float, bool]:
        """Wait for a stable match; returns (match or None, best score, skipped).

        With `skip`, give up early (skipped=True) once that screen has been showing for SKIP_SETTLE.
        """
        started = self.clock()
        deadline = started + timeout
        streak: list[Match] = []
        best = 0.0
        skip_since: float | None = None
        while True:
            frame = self._frame()
            match = find_anchor(to_work(frame), anchor)
            best = max(best, match.score)
            if match.score < threshold:
                streak = []
            elif streak and all(abs(a - b) <= STABLE for a, b in zip(streak[-1].shift, match.shift)):
                streak.append(match)
            else:
                streak = [match]
            needed = CONFIRM_LONG if self.clock() - started > LONG_WAIT else CONFIRM
            if len(streak) >= needed:
                return match, best, False
            if skip is not None and not streak and skip(frame):
                skip_since = self.clock() if skip_since is None else skip_since
                if self.clock() - skip_since >= SKIP_SETTLE:
                    return None, best, True
            elif skip is not None:
                skip_since = None
            if self.clock() >= deadline:
                return None, best, False
            self._sleep(POLL)

    def _wait_screen(self, reference: np.ndarray, timeout: float) -> tuple[bool, float]:
        deadline = self.clock() + timeout
        confirmed = 0
        score = 0.0
        while True:
            score = screen_similarity(self._frame(), reference)
            confirmed = confirmed + 1 if score >= SAME_SCREEN else 0
            if confirmed >= 2:
                return True, score
            if self.clock() >= deadline:
                return False, score
            self._sleep(POLL)

    def _next_screen(self, index: int) -> Callable[[np.ndarray], bool] | None:
        """Test for the screen that should follow step `index`, if one can be checked."""
        steps = self.flow.steps
        if index + 1 < len(steps):
            following = steps[index + 1]
            if not following.check:
                return None
            anchor = make_anchor(self._image(following.image), following.check_point)
            return lambda frame: find_anchor(to_work(frame), anchor).score >= following.threshold_value
        if self.flow.end_check and self.flow.end_image:
            if self.flow.end_look:
                end = make_anchor(self._image(self.flow.end_image), tuple(self.flow.end_look))
                return lambda frame: find_anchor(to_work(frame), end).score >= MATCH_THRESHOLD
            reference = self._image(self.flow.end_image)
            return lambda frame: screen_similarity(frame, reference) >= SAME_SCREEN
        return None

    def _wait_until(self, arrived: Callable[[np.ndarray], bool], timeout: float) -> bool:
        deadline = self.clock() + timeout
        while not arrived(self._frame()):
            if self.clock() >= deadline:
                return False
            self._sleep(POLL)
        return True

    def ready(self, timeout: float) -> bool:
        """Whether the flow's start screen is showing (first step's check), without touching anything."""
        step = self.flow.steps[0]
        if step.check:
            anchor = make_anchor(self._image(step.image), step.check_point)
            return self._wait_anchor(anchor, step.threshold_value, timeout)[0] is not None
        return self._wait_screen(self._image(step.image), timeout)[0]

    def _check(self, step: Step, index: int, outcome: StepResult, size: tuple[int, int]) -> str:
        """Wait until it is safe to act; returns an error message instead when it is not."""
        if step.check:
            timeout = step.timeout_for(index)
            anchor = make_anchor(self._image(step.image), step.check_point)
            skip = self._next_screen(index) if step.optional else None
            match, best, skipped = self._wait_anchor(anchor, step.threshold_value, timeout, skip)
            outcome.score = round(match.score if match else best, 3)
            if skipped:
                outcome.status = "skipped"
                return ""
            if match is None:
                return (
                    f"{timeout:.0f}s 内没有出现录制时触点处的画面"
                    f"（最高匹配 {best:.2f}，需要 {step.threshold_value:.2f}）"
                )
            if step.tap_follows_check(min(self.flow.size), ANCHOR_SIDE):
                outcome.shift = [round(v, 1) for v in match.shift_in(size)]
        elif index == 0:
            same, similarity = self._wait_screen(self._image(step.image), step.timeout_for(index))
            outcome.score = round(similarity, 3)
            if not same:
                return f"当前画面不是录制起点（相似度 {similarity:.2f}）"
        return ""

    def _act(self, step: Step, index: int, points: list[list[float]], outcome: StepResult) -> str:
        """Perform the gesture; until_next steps repeat it until the next screen appears.

        A checked step is only tapped again while its own screen is still showing (the tap
        did not take); once that screen is gone, extra taps could land on whatever comes next,
        so it just waits for the expected screen. Empty-spot steps retap blindly: the spot was empty.
        """
        arrived = self._next_screen(index) if step.until_next else None
        self.device.gesture(points, self.stop)
        outcome.taps = 1
        if arrived is None:
            return ""
        still_here = None
        if step.check:
            anchor = make_anchor(self._image(step.image), step.check_point)
            still_here = lambda frame: find_anchor(to_work(frame), anchor).score >= step.threshold_value  # noqa: E731
        for _ in range(RETRY_TAPS):
            if self._wait_until(arrived, RETRY_WAIT):
                return ""
            if outcome.taps >= RETRY_TAPS:
                break
            if still_here is not None and not still_here(self.last_frame):
                continue  # left this screen: wait for the next one without tapping
            self.device.gesture(points, self.stop)
            outcome.taps += 1
        return f"点了 {outcome.taps} 次，等了 {RETRY_WAIT * RETRY_TAPS:.0f}s，下一画面仍未出现"

    def _react(self, first: int, last: int, size: tuple[int, int], scale: float, result: RunResult) -> str:
        """Run react steps first..last (0-based) until the screen after the block shows up."""
        steps, total = self.flow.steps, len(self.flow.steps)
        goal = self._next_screen(last)
        if goal is None:
            return "应对步骤之后的一步需要检查画面（或流程有结束画面），否则不知道何时结束"
        block = range(first, last + 1)
        handlers = [
            (k, make_anchor(self._image(steps[k].image), steps[k].check_point))
            for k in block
            if steps[k].check
        ]
        nudges = [k for k in block if not steps[k].check]
        patience = max(steps[k].timeout_for(k) for k in block)
        progress_at = self.clock()
        fired = nudged = 0
        seen: object = None
        streak = 0
        while True:
            frame = self._frame()
            work = to_work(frame)
            key: object = "goal" if goal(frame) else None
            match = None
            if key is None:
                for k, anchor in handlers:
                    candidate = find_anchor(work, anchor)
                    if candidate.score >= steps[k].threshold_value:
                        key, match = k, candidate
                        break
            streak = streak + 1 if key is not None and key == seen else (1 if key is not None else 0)
            seen = key
            if key == "goal" and streak >= CONFIRM:
                return ""
            nudge = (
                key is None
                and nudges
                and fired
                and nudged < NUDGE_MAX
                and self.clock() - progress_at >= NUDGE_AFTER
            )
            if (key is not None and key != "goal" and streak >= CONFIRM) or nudge:
                if fired + nudged >= REACT_MAX:
                    return f"应对步骤已执行 {REACT_MAX} 次，画面仍未进入下一步"
                k = nudges[0] if nudge else key
                step = steps[k]
                shot = f"react-{len(result.shots) + 1:02d}.jpg"  # the screen as it was before reacting
                save_jpeg(self._run_dir / shot, frame)
                result.shots.append(shot)
                dx, dy = (0.0, 0.0)
                if match is not None and step.tap_follows_check(min(self.flow.size), ANCHOR_SIDE):
                    dx, dy = match.shift_in(size)
                self.device.gesture(
                    [[t, x * scale + dx, y * scale + dy] for t, x, y in step.points], self.stop
                )
                score = None if match is None else round(match.score, 3)
                result.steps.append(
                    StepResult(k + 1, "done", score, taps=1, shift=[round(dx, 1), round(dy, 1)])
                )
                why = "没有可识别的画面，轻点一下继续" if nudge else f"画面出现，应对（匹配 {score:.2f}）"
                self.log(f"[{k + 1}/{total}] ↻ {step.describe()}  {why}，截图 {shot}")
                if nudge:
                    nudged += 1
                else:
                    fired += 1
                progress_at, seen, streak = self.clock(), None, 0
                self._sleep(REACT_SETTLE)
                continue
            if self.clock() - progress_at >= patience:
                return f"{patience:.0f}s 内既没有可应对的画面，也没有进入下一步"
            self._sleep(POLL)

    def run(self, run_dir: Path) -> RunResult:
        flow = self.flow
        result = RunResult(flow.name, flow.revision, datetime.now().isoformat(timespec="seconds"))
        started = self.clock()
        total = len(flow.steps)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._run_dir = run_dir
        try:
            width, height = self.device.size
            rec_w, rec_h = flow.size
            if abs(width / height - rec_w / rec_h) > 0.01:
                raise DeviceError(
                    f"当前画面 {width}x{height} 与录制时 {rec_w}x{rec_h} 比例不同（横竖屏?），无法回放"
                )
            scale = width / rec_w
            i = self.start - 1
            while i < total:
                step = flow.steps[i]
                number = i + 1
                if step.react:
                    last = i
                    while last + 1 < total and flow.steps[last + 1].react:
                        last += 1
                    error = self._react(i, last, (width, height), scale, result)
                    if error:
                        result.status, result.reason = (
                            "failed",
                            f"第 {number}–{last + 1} 步（应对）：{error}；已停止",
                        )
                        self.log(f"[{number}–{last + 1}/{total}] ✗ {error}")
                        break
                    i = last + 1
                    continue
                begun = self.clock()
                self._sleep(step.delay_for(i))
                outcome = StepResult(number, "done")
                error = self._check(step, i, outcome, (width, height))
                outcome.waited = round(self.clock() - begun, 2)
                if outcome.status == "skipped":
                    result.steps.append(outcome)
                    self.log(
                        f"[{number}/{total}] ↷ 跳过 {step.describe()}：没出现（可选），下一步的画面已就绪"
                    )
                    i += 1
                    continue
                if not error:
                    dx, dy = outcome.shift
                    points = [[t, x * scale + dx, y * scale + dy] for t, x, y in step.points]
                    error = self._act(step, i, points, outcome)
                result.steps.append(outcome)
                if error:
                    outcome.status, outcome.error = "failed", error
                    rest = "没有执行任何操作" if i == 0 and not outcome.taps else "后续步骤未执行"
                    result.status, result.reason = "failed", f"第 {number} 步：{error}；已停止，{rest}"
                    self.log(f"[{number}/{total}] ✗ {step.describe()}  {error}")
                    break
                if step.check:
                    check = f"画面匹配 {outcome.score:.2f}"
                elif step.until_next:
                    check = f"空白处，点了 {outcome.taps} 次进入下一画面"
                else:
                    check = "按录制节奏，未检查画面"
                moved = f"，位置偏移 ({dx:+.0f},{dy:+.0f})" if (dx, dy) != (0, 0) else ""
                self.log(
                    f"[{number}/{total}] ✓ {step.describe()}  等待 {outcome.waited:.1f}s，{check}{moved}"
                )
                i += 1
            else:
                if flow.end_check and flow.end_image:
                    if flow.end_look:
                        end = make_anchor(self._image(flow.end_image), tuple(flow.end_look))
                        match, similarity, _ = self._wait_anchor(end, MATCH_THRESHOLD, flow.end_timeout())
                        same = match is not None
                    else:
                        same, similarity = self._wait_screen(self._image(flow.end_image), flow.end_timeout())
                    result.end_score = round(similarity, 3)
                    if same:
                        result.status, result.reason = (
                            "success",
                            f"全部 {total} 步完成，结束画面一致（{similarity:.2f}）",
                        )
                    else:
                        result.status = "failed"
                        result.reason = f"操作都已执行，但 {flow.end_timeout():.0f}s 内最终画面与录制结束时不一致（{similarity:.2f}）"
                else:
                    result.status, result.reason = "success", f"全部 {total} 步完成（未检查结束画面）"
        except (Interrupted, KeyboardInterrupt):
            result.status, result.reason = "stopped", "手动停止；当前手势已松开，后续步骤未执行"
        except DeviceError as exc:
            result.status, result.reason = "error", str(exc)
        result.seconds = round(self.clock() - started, 2)
        run_dir.mkdir(parents=True, exist_ok=True)
        if self.last_frame is not None:
            save_jpeg(run_dir / "last.jpg", self.last_frame)
            result.image = "last.jpg"
        (run_dir / "run.json").write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return result

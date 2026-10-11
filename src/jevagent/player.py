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
from jevagent.flow import Flow
from jevagent.recorder import save_jpeg
from jevagent.vision import SAME_SCREEN, Anchor, Match, find_anchor, make_anchor, screen_similarity, to_work

STATUS = {"success": "成功", "failed": "失败", "stopped": "已停止", "error": "出错", "running": "未完成"}
POLL = 0.05  # pause between frames while waiting (a frame itself takes ~0.1 s)
STABLE = 3  # work pixels the anchor may move between the two frames that confirm it


@dataclass
class StepResult:
    step: int  # 1-based
    status: str  # done | failed
    score: float | None = None  # anchor match, or start-screen similarity for an unchecked first step
    waited: float = 0.0  # seconds from the end of the previous step until this gesture started
    shift: list[float] = field(default_factory=lambda: [0.0, 0.0])
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
    ) -> None:
        self.device, self.flow, self.folder, self.log, self.clock = device, flow, folder, log, clock
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

    def _wait_anchor(self, anchor: Anchor, threshold: float, timeout: float) -> tuple[Match | None, float]:
        deadline = self.clock() + timeout
        previous: Match | None = None
        best = 0.0
        while True:
            match = find_anchor(to_work(self._frame()), anchor)
            best = max(best, match.score)
            if match.score >= threshold:
                if previous is not None and all(
                    abs(a - b) <= STABLE for a, b in zip(previous.shift, match.shift)
                ):
                    return match, best
                previous = match
            else:
                previous = None
            if self.clock() >= deadline:
                return None, best
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

    def run(self, run_dir: Path) -> RunResult:
        flow = self.flow
        result = RunResult(flow.name, flow.revision, datetime.now().isoformat(timespec="seconds"))
        started = self.clock()
        total = len(flow.steps)
        try:
            width, height = self.device.size
            rec_w, rec_h = flow.size
            if abs(width / height - rec_w / rec_h) > 0.01:
                raise DeviceError(
                    f"当前画面 {width}x{height} 与录制时 {rec_w}x{rec_h} 比例不同（横竖屏?），无法回放"
                )
            scale = width / rec_w
            for i, step in enumerate(flow.steps):
                number = i + 1
                begun = self.clock()
                self._sleep(step.delay_for(i))
                outcome = StepResult(number, "done")
                error = ""
                if step.check:
                    timeout = step.timeout_for(i)
                    anchor = make_anchor(self._image(step.image), step.points[0][1:])
                    match, best = self._wait_anchor(anchor, step.threshold_value, timeout)
                    outcome.score = round(match.score if match else best, 3)
                    if match is None:
                        error = (
                            f"{timeout:.0f}s 内没有出现录制时触点处的画面"
                            f"（最高匹配 {best:.2f}，需要 {step.threshold_value:.2f}）"
                        )
                    else:
                        outcome.shift = [round(v, 1) for v in match.shift_in((width, height))]
                elif i == 0:
                    same, similarity = self._wait_screen(self._image(step.image), step.timeout_for(i))
                    outcome.score = round(similarity, 3)
                    if not same:
                        error = f"当前画面不是录制起点（相似度 {similarity:.2f}）"
                outcome.waited = round(self.clock() - begun, 2)
                if error:
                    outcome.status, outcome.error = "failed", error
                    result.steps.append(outcome)
                    rest = "没有执行任何操作" if i == 0 else "后续步骤未执行"
                    result.status, result.reason = "failed", f"第 {number} 步：{error}；已停止，{rest}"
                    self.log(f"[{number}/{total}] ✗ {step.describe()}  {error}")
                    break
                dx, dy = outcome.shift
                points = [[t, x * scale + dx, y * scale + dy] for t, x, y in step.points]
                self.device.gesture(points, self.stop)
                result.steps.append(outcome)
                check = f"画面匹配 {outcome.score:.2f}" if step.check else "按录制节奏，未检查画面"
                moved = f"，位置偏移 ({dx:+.0f},{dy:+.0f})" if (dx, dy) != (0, 0) else ""
                self.log(
                    f"[{number}/{total}] ✓ {step.describe()}  等待 {outcome.waited:.1f}s，{check}{moved}"
                )
            else:
                if flow.end_check and flow.end_image:
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

"""Record a flow while you play: gestures from the touchscreen + the screen before each one."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from jevagent.errors import DeviceError
from jevagent.flow import Flow, Step
from jevagent.touch import Gesture, GestureParser, TouchScreen, natural_to_up, parse_event
from jevagent.vision import MIN_TEXTURE, make_anchor

TAP_SLOP = 0.02  # movement under this fraction of the short side still counts as a tap
QUICK_FOLLOW_UP = 0.6  # seconds; faster follow-ups are replayed on the recorded rhythm, unchecked
PRE_TOUCH = 0.1  # the reference frame must have arrived this long before touch-down
JPEG_QUALITY = 95
RAW_LOG = "getevent.log"


def save_jpeg(path: Path, frame: np.ndarray) -> None:
    if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]):
        raise OSError(f"无法写入 {path}")


class FrameBuffer:
    """The last few frames with their arrival time (host monotonic clock)."""

    def __init__(self, maxlen: int = 24) -> None:
        self._items: deque[tuple[float, np.ndarray]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, t: float, frame: np.ndarray) -> None:
        with self._lock:
            self._items.append((t, frame))

    def before(self, t: float) -> tuple[float, np.ndarray] | None:
        """Newest frame that arrived at or before t (else the oldest one kept)."""
        with self._lock:
            items = list(self._items)
        if not items:
            return None
        older = [item for item in items if item[0] <= t]
        return older[-1] if older else items[0]


def screen_points(
    gesture: Gesture, screen: TouchScreen, natural: tuple[int, int], orientation: int, size: tuple[int, int]
) -> list[list[float]]:
    """Raw gesture -> [[t, x, y]] in screenshot pixels; taps collapse to press/release."""
    width, height = size
    points = []
    for t, raw_x, raw_y in gesture.points:
        x, y = natural_to_up(screen.to_natural(raw_x, raw_y, natural), natural, orientation)
        points.append(
            [
                round(t - gesture.start, 3),
                round(min(max(x, 0), width - 1), 1),
                round(min(max(y, 0), height - 1), 1),
            ]
        )
    x0, y0 = points[0][1:]
    slop = TAP_SLOP * min(size)
    if all(math.hypot(x - x0, y - y0) <= slop for _, x, y in points):
        return [[0.0, x0, y0], [points[-1][0], x0, y0]]
    kept = [points[0]]
    for point in points[1:-1]:
        if point[0] - kept[-1][0] >= 1 / 60:
            kept.append(point)
    return kept + [points[-1]]


class Recorder:
    """Runs a frame grabber and a getevent reader in background threads.

    The device must provide frame(), size, display(), touchscreen() and getevent(path).
    """

    def __init__(
        self,
        device,
        folder: Path,
        log: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.device, self.folder, self.log, self.clock = device, folder, log, clock
        self.frames = FrameBuffer()
        self.steps: list[Step] = []
        self.skipped = 0
        self.error: str | None = None
        self._stop = threading.Event()
        self._last_up: float | None = None
        self._threads: list[threading.Thread] = []
        self._proc = None

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.screen = self.device.touchscreen()
        self.natural, self.orientation = self.device.display()
        self.frames.add(self.clock(), self.device.frame())  # first frame also starts the capture stream
        self.size = self.device.size
        self._proc = self.device.getevent(self.screen.path)
        self.started = self.clock()
        for target in (self._grab_frames, self._read_events):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)

    def _fail(self, message: str) -> None:
        if not self._stop.is_set() and self.error is None:
            self.error = message
            self.log(f"录制出错：{message}。按 Enter 结束（已录的步骤会保留）")

    def _grab_frames(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self.device.frame()
            except Exception as exc:
                self._fail(f"截图中断: {exc}")
                return
            self.frames.add(self.clock(), frame)

    def _read_events(self) -> None:
        parser = GestureParser()
        offset = math.inf  # host clock - device clock, least-delayed sample
        pending: tuple[float, np.ndarray] | None = None
        # Raw stream with arrival times, kept with the flow for diagnosing touch parsing.
        with open(self.folder / RAW_LOG, "w", encoding="utf-8") as raw:
            for line in self._proc.stdout:
                now = self.clock()
                raw.write(f"{now:.4f} {line.rstrip()}\n")
                event = parse_event(line)
                if event is None:
                    if any(word in line.lower() for word in ("denied", "could not", "error", "not found")):
                        self.log(f"getevent: {line.strip()}")
                    continue
                offset = min(offset, now - event.time)
                gesture = parser.push(event)
                if pending is None and parser.touching_since is not None:
                    # Pick the reference frame at touch-down; long holds would push it out of the buffer.
                    pending = self.frames.before(parser.touching_since + offset - PRE_TOUCH)
                if gesture is not None:
                    try:
                        self.add(gesture, offset, pending)
                    except Exception as exc:
                        self._fail(f"保存步骤失败: {exc}")
                    pending = None
        self._fail("getevent 已退出，手机可能断开了")

    def add(self, gesture: Gesture, offset: float, pre: tuple[float, np.ndarray] | None) -> Step | None:
        if gesture.fingers > 1 or not gesture.complete or pre is None:
            self.skipped += 1
            if gesture.fingers > 1:
                self.log("  （忽略一次多指操作，M0 只录单指手势）")
            else:
                self.log("  （忽略一次触摸：没有读到坐标或画面）")
            return None
        down, up = gesture.start + offset, gesture.end + offset
        gap = down - (self._last_up if self._last_up is not None else self.started)
        self._last_up = up
        index = len(self.steps) + 1
        points = screen_points(gesture, self.screen, self.natural, self.orientation, self.size)
        frame = pre[1]
        step = Step(points=points, gap=round(max(gap, 0.0), 2), image=f"step-{index:02d}.jpg")
        if index > 1 and gap < QUICK_FOLLOW_UP:
            step.check, step.note = False, f"距上一步仅 {gap:.1f}s，按录制节奏执行"
        elif make_anchor(frame, points[0][1:]).texture < MIN_TEXTURE:
            # Usually "tap anywhere to continue/close": keep tapping until the next screen shows.
            step.check, step.until_next = False, True
            step.note = "点在空白处：回放时点到下一画面出现为止"
        save_jpeg(self.folder / step.image, frame)
        self.steps.append(step)
        flag = "" if step.check else f"  [不检查画面：{step.note}]"
        self.log(f"  #{index} {step.describe()}  间隔 {step.gap:.1f}s{flag}")
        return step

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
        for thread in self._threads:
            thread.join(timeout=5)

    def finish(self, name: str) -> Flow:
        """Stop, capture the end screen, return the flow (not yet saved)."""
        self.stop()
        end_gap = self.clock() - (self._last_up if self._last_up is not None else self.started)
        end_image = "end.jpg"
        try:
            save_jpeg(self.folder / end_image, self.device.frame())
        except DeviceError as exc:  # keep the recorded steps; just skip the end check
            self.error = self.error or f"结束画面没截到: {exc}"
            end_image = None
        device = {
            "serial": getattr(self.device, "serial", ""),
            "model": getattr(getattr(self.device, "info", None), "model", ""),
        }
        return Flow(
            name=name,
            size=list(self.size),
            steps=self.steps,
            end_image=end_image,
            end_gap=round(end_gap, 2),
            end_check=end_image is not None,
            device=device,
        )

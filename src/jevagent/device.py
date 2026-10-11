"""Android phone over USB ADB: pick the device, read frames, inject gestures, stream raw touches.

Device selection, the display/orientation reading and the backend choice
(MINICAP_APK screenshots, MAXTOUCH input) follow hawarma's src/hawarma/device.py,
which was verified with the same Airtest fork on the HONOR ELZ_AN00 in this game.
Input only ever goes to the serial that was selected; nothing is retried or replayed
after an error.
"""

from __future__ import annotations

import functools
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

with warnings.catch_warnings():
    warnings.simplefilter("ignore", SyntaxWarning)  # the fork's regex strings use invalid escapes
    from airtest.core.android.adb import ADB
    from airtest.core.android.cap_methods.screen_proxy import ScreenProxy
    from airtest.core.android.touch_methods.base_touch import DownEvent, MoveEvent, UpEvent
    from airtest.core.android.touch_methods.touch_proxy import TouchProxy

from jevagent.errors import DeviceError, Interrupted
from jevagent.touch import TouchScreen, parse_input_devices, pick_touchscreen, up_to_natural

logging.getLogger("airtest").setLevel(logging.WARNING)

DISPLAY_CHECK_INTERVAL = 0.5  # seconds between orientation/size checks (one dumpsys, ~0.1 s)

__all__ = ["AndroidDevice", "DeviceError", "DeviceInfo", "Interrupted", "list_devices", "resolve_adb"]


def _stop_on_failure(action: str):
    """Any adb/Airtest failure (e.g. the cable was pulled) becomes a DeviceError: stop, never retry."""

    def wrap(method):
        @functools.wraps(method)
        def call(*args, **kwargs):
            try:
                return method(*args, **kwargs)
            except (DeviceError, Interrupted, KeyboardInterrupt):
                raise
            except Exception as exc:
                raise DeviceError(f"{action}失败，手机可能已断开: {exc}") from exc

        return call

    return wrap


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    state: str
    model: str = "unknown"


def parse_devices(output: str) -> list[DeviceInfo]:
    result = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or line.startswith(("List of devices", "*")):
            continue
        attrs = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        result.append(DeviceInfo(parts[0], parts[1], attrs.get("model", "unknown")))
    return result


def resolve_adb(path: str | None = None) -> str:
    """Explicit path > adb on PATH > the adb bundled with Airtest."""
    candidate = Path(path or shutil.which("adb") or ADB.get_adb_path()).expanduser().resolve()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise DeviceError(f"找不到可执行的 adb: {candidate}；brew install --cask android-platform-tools")
    return str(candidate)


def list_devices(adb_path: str, timeout: float = 10.0) -> list[DeviceInfo]:
    try:
        out = subprocess.run(
            [adb_path, "devices", "-l"], capture_output=True, text=True, timeout=timeout, check=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeviceError(f"adb devices 失败: {exc}") from exc
    return parse_devices(out.stdout)


def pick_device(devices: list[DeviceInfo], serial: str | None) -> DeviceInfo:
    if serial:
        match = next((d for d in devices if d.serial == serial), None)
        if match is None:
            raise DeviceError(f"设备 {serial} 不在线；不会改用其他设备")
        candidates = [match]
    else:
        candidates = devices
    if not candidates:
        raise DeviceError("没有发现设备：用数据线连接手机，打开 USB 调试并在手机上允许这台电脑")
    if len(candidates) > 1:
        raise DeviceError("有多台设备，请用 --serial 指定: " + ", ".join(d.serial for d in candidates))
    device = candidates[0]
    if device.state == "unauthorized":
        raise DeviceError(f"{device.serial} 未授权：解锁手机，在弹窗里允许 USB 调试")
    if device.state != "device":
        raise DeviceError(f"{device.serial} 状态为 {device.state}：重新插线后再试")
    return device


class _ADB(ADB):
    """Airtest ADB bound to one serial, with a command timeout and hawarma's display fixes."""

    def __init__(self, serial: str, path: str, timeout: float) -> None:
        self.command_timeout = timeout
        super().__init__(serialno=serial, adb_path=path)

    def connect(self, force: bool = False) -> None:  # never `adb connect` implicitly
        return None

    def cmd(self, cmds, device=True, ensure_unicode=True, timeout=None):
        return super().cmd(
            cmds,
            device=device,
            ensure_unicode=ensure_unicode,
            timeout=min(timeout or self.command_timeout, self.command_timeout),
        )

    def display_frames(self) -> tuple[int, int, int] | None:
        """(width, height, rotation) of display 0 in its current orientation.

        minicap adds a virtual display that can be listed first, so only the
        mDisplayId=0 section is read.
        """
        sections = re.split(r"Display: mDisplayId=", self.cmd(["shell", "dumpsys", "window", "displays"]))
        section = next((s for s in sections[1:] if re.match(r"0\b", s)), "")
        match = re.search(r"DisplayFrames[^\n]*?w=(\d+)[^\n]*?h=(\d+)[^\n]*?r=(\d+)", section)
        return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None

    def getDisplayOrientation(self) -> int:
        frames = self.display_frames()
        if frames and frames[2] in (0, 1, 2, 3):
            return frames[2]
        for command, pattern in (
            (["shell", "dumpsys", "input"], r"SurfaceOrientation:\s+(\d+)"),
            (["shell", "dumpsys", "SurfaceFlinger"], r"orientation=(\d+)"),
        ):
            match = re.search(pattern, self.cmd(command))
            if match and int(match.group(1)) in (0, 1, 2, 3):
                return int(match.group(1))
        raise DeviceError("无法读取屏幕方向")

    def get_display_info(self) -> dict[str, int]:
        frames = self.display_frames()
        if frames is None or frames[2] not in (0, 1, 2, 3):
            return super().get_display_info()
        width, height, orientation = frames
        if orientation in (1, 3):
            width, height = height, width
        max_x, max_y = self.getMaxXY()
        return {
            "width": width,
            "height": height,
            "orientation": orientation,
            "rotation": orientation * 90,
            "max_x": max_x,
            "max_y": max_y,
        }


class AndroidDevice:
    """One USB phone. Frames and gestures use screenshot (upright) pixel coordinates."""

    def __init__(
        self,
        serial: str | None = None,
        adb_path: str | None = None,
        capture: str = "MINICAP_APK",
        timeout: float = 10.0,
    ) -> None:
        self.adb_path = resolve_adb(adb_path)
        self.info = pick_device(list_devices(self.adb_path, timeout), serial)
        self.serial = self.info.serial
        self.timeout = timeout
        self.adb = _ADB(self.serial, self.adb_path, timeout)
        self.capture_method = capture
        self.touch_method: str | None = None
        self._capture = None
        self._touch = None
        self._natural = (0, 0)
        self._lock = threading.RLock()
        self._size: tuple[int, int] | None = None
        self._orientation: int | None = None
        self._checked_at = float("-inf")
        self.last_frame_seconds = 0.0

    # -- reading ---------------------------------------------------------------------------
    @_stop_on_failure("读取屏幕方向")
    def display(self) -> tuple[tuple[int, int], int]:
        """Natural (portrait) display size and current rotation 0-3."""
        frames = self.adb.display_frames()
        if frames is None:
            info = self.adb.get_display_info()
            return (info["width"], info["height"]), info["orientation"]
        width, height, orientation = frames
        return ((height, width) if orientation in (1, 3) else (width, height)), orientation

    @property
    def size(self) -> tuple[int, int]:
        if self._size is None:
            self.frame()
        assert self._size is not None
        return self._size

    @_stop_on_failure("截图")
    def frame(self) -> np.ndarray:
        """Latest screen as a BGR array; stops on rotation or resolution changes."""
        with self._lock:
            now = time.monotonic()
            orientation = self._orientation
            if orientation is None or now - self._checked_at >= DISPLAY_CHECK_INTERVAL:
                orientation = self.adb.getDisplayOrientation()
                self._checked_at = now
            if self._capture is None:
                method = ScreenProxy.SCREEN_METHODS.get(self.capture_method)
                if method is None:
                    raise DeviceError(f"Airtest 不支持截图方式 {self.capture_method}")
                self._capture = method(self.adb)
                self._capture.RECVTIMEOUT = self.timeout
            started = time.perf_counter()
            try:
                frame = self._capture.snapshot(ensure_orientation=True)
            except Exception as exc:
                raise DeviceError(f"截图失败: {exc}") from exc
            self.last_frame_seconds = time.perf_counter() - started
            if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3 or not frame.any():
                raise DeviceError("截图为空或全黑：解锁手机并打开游戏")
            size = (frame.shape[1], frame.shape[0])
            if self._size is not None and (size, orientation) != (self._size, self._orientation):
                raise DeviceError(
                    f"屏幕尺寸/方向变了: {self._size}/{self._orientation} → {size}/{orientation}；"
                    "固定横屏后重新开始"
                )
            self._size, self._orientation = size, orientation
            return frame

    @_stop_on_failure("读取触摸屏")
    def touchscreen(self) -> TouchScreen:
        text = self.adb.cmd(["shell", "getevent", "-p"])
        screen = pick_touchscreen(parse_input_devices(text))
        if screen is None:
            raise DeviceError("getevent 没有列出触摸屏（需要 ABS_MT_POSITION_X/Y）")
        return screen

    def getevent(self, path: str) -> subprocess.Popen:
        """Stream raw events of one input device.

        `-t -t` forces a pty so getevent's output is line-buffered and arrives as it happens.
        """
        return subprocess.Popen(
            [self.adb_path, "-s", self.serial, "shell", "-t", "-t", "getevent", "-t", path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    # -- input -----------------------------------------------------------------------------
    @_stop_on_failure("启动触摸服务")
    def prepare_input(self) -> str:
        """Start the touch service before replaying, so the first gesture is not delayed."""
        with self._lock:
            self._setup_touch()
        return self.touch_method or ""

    def _setup_touch(self) -> None:
        if self._touch is not None:
            return
        method = "MAXTOUCH" if self.adb.sdk_version >= 29 else "MINITOUCH"
        info = self.adb.get_display_info()
        expected = (
            (info["height"], info["width"])
            if info["orientation"] in (1, 3)
            else (info["width"], info["height"])
        )
        if expected != self.size:
            raise DeviceError(f"显示信息 {expected} 与截图 {self.size} 不一致，拒绝输入")
        touch = TouchProxy.TOUCH_METHODS[method].METHOD_CLASS(self.adb, size_info=info)
        try:
            touch.install_and_setup()
            touch.client.sock.settimeout(self.timeout)
            # Airtest's safe_send reconnects and resends on errors; a gesture must never be replayed.
            touch.handle = lambda data: touch.client.send(data.encode("utf-8"))
        except Exception as exc:
            raise DeviceError(f"触摸初始化失败 ({method}): {exc}") from exc
        self._touch, self.touch_method, self._natural = touch, method, (info["width"], info["height"])

    @_stop_on_failure("触摸")
    def gesture(self, points: Sequence[Sequence[float]], stop: threading.Event | None = None) -> None:
        """Press at points[0], follow the path with its timing, release. points: (t, x, y)."""
        with self._lock:
            self._setup_touch()
            orientation = self.adb.getDisplayOrientation()
            if orientation != self._orientation:
                raise DeviceError("屏幕方向变了，已停止")
            width, height = self.size
            for _, x, y in points:
                if not (0 <= x < width and 0 <= y < height):
                    raise DeviceError(f"触点 ({x:.0f},{y:.0f}) 超出屏幕 {width}x{height}")
            touch = self._touch
            natural = [up_to_natural((x, y), self._natural, orientation) for _, x, y in points]
            pressed = False
            try:
                touch.perform([DownEvent(natural[0], pressure=touch.default_pressure)])
                pressed = True
                for i in range(1, len(points)):
                    wait = max(points[i][0] - points[i - 1][0], 0)
                    if stop is None:
                        time.sleep(wait)
                    elif stop.wait(wait):
                        raise Interrupted("已停止")
                    if natural[i] != natural[i - 1]:
                        touch.perform([MoveEvent(natural[i], pressure=touch.default_pressure)])
                touch.perform([UpEvent()])
                pressed = False
            except (Exception, KeyboardInterrupt) as exc:
                if pressed:
                    try:
                        touch.perform([UpEvent()])
                    except Exception:
                        pass
                if isinstance(exc, (KeyboardInterrupt, Interrupted)):
                    raise
                raise DeviceError(f"手势发送失败，未重试: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            for resource, method in ((self._touch, "teardown"), (self._capture, "teardown_stream")):
                if resource is not None:
                    try:
                        getattr(resource, method)()
                    except Exception:
                        pass
            self._touch = self._capture = None

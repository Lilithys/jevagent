"""Turn the phone's raw touchscreen events (`adb shell getevent`) into gestures.

You demonstrate on the phone itself, so the recording sees exactly what your
finger did: where, how long, and the path of a swipe. Both Linux multi-touch
protocols are handled:

* B (slots): contacts live in ABS_MT_SLOT slots, a tracking id of -1 lifts one.
* A (no slots): every frame lists all current contacts, each closed by SYN_MT_REPORT;
  a lifted finger is simply missing. The HONOR ELZ_AN00's "input_mt_wrapper" works this way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT, SYN_MT_REPORT = 0x00, 0x02
BTN_TOUCH = 0x14A
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x2F, 0x35, 0x36, 0x39
_KEYS = {ABS_MT_TRACKING_ID: "id", ABS_MT_POSITION_X: "x", ABS_MT_POSITION_Y: "y"}


@dataclass(frozen=True)
class TouchScreen:
    path: str
    name: str
    x_range: tuple[int, int]
    y_range: tuple[int, int]
    direct: bool = True
    slots: bool = True  # multi-touch protocol B; False means protocol A

    @property
    def protocol(self) -> str:
        return "B（slot）" if self.slots else "A（无 slot）"

    def to_natural(self, x: int, y: int, natural_size: tuple[int, int]) -> tuple[float, float]:
        """Raw panel units -> display pixels in the phone's natural (portrait) orientation."""
        (x0, x1), (y0, y1) = self.x_range, self.y_range
        width, height = natural_size
        return (x - x0) * width / (x1 - x0 + 1), (y - y0) * height / (y1 - y0 + 1)


def parse_input_devices(text: str) -> list[TouchScreen]:
    """Touchscreens listed by `getevent -p` (numeric codes)."""
    screens = []
    for block in re.split(r"^add device \d+: ", text, flags=re.M)[1:]:
        path = block.split(None, 1)[0]
        name = re.search(r'name:\s+"(.*)"', block)
        axes = {
            int(code, 16): (int(low), int(high))
            for code, low, high in re.findall(
                r"\b([0-9a-f]{4})\s*: value -?\d+, min (-?\d+), max (-?\d+)", block
            )
        }
        if ABS_MT_POSITION_X in axes and ABS_MT_POSITION_Y in axes:
            screens.append(
                TouchScreen(
                    path,
                    name.group(1) if name else "",
                    axes[ABS_MT_POSITION_X],
                    axes[ABS_MT_POSITION_Y],
                    "INPUT_PROP_DIRECT" in block,
                    ABS_MT_SLOT in axes,
                )
            )
    return screens


def pick_touchscreen(screens: list[TouchScreen]) -> TouchScreen | None:
    return next((s for s in screens if s.direct), screens[0] if screens else None)


def up_to_natural(point: tuple[float, float], natural_size: tuple[int, int], orientation: int):
    """Screenshot (upright) pixels -> natural orientation; same math as Airtest's XYTransformer."""
    x, y = point
    w, h = natural_size
    if orientation == 1:
        return w - y, x
    if orientation == 2:
        return w - x, h - y
    if orientation == 3:
        return y, h - x
    return x, y


def natural_to_up(point: tuple[float, float], natural_size: tuple[int, int], orientation: int):
    x, y = point
    w, h = natural_size
    if orientation == 1:
        return y, w - x
    if orientation == 2:
        return w - x, h - y
    if orientation == 3:
        return h - y, x
    return x, y


@dataclass(frozen=True)
class RawEvent:
    time: float  # device CLOCK_MONOTONIC seconds
    type: int
    code: int
    value: int


_EVENT = re.compile(r"^\[\s*(\d+)\.(\d+)\]\s+(?:\S+:\s+)?([0-9a-f]{4})\s+([0-9a-f]{4})\s+([0-9a-f]{8})\s*$")


def parse_event(line: str) -> RawEvent | None:
    """One line of `getevent -t` output, e.g. `[   20517.358413] 0003 0035 0000021e`."""
    match = _EVENT.match(line.strip())
    if not match:
        return None
    sec, usec, kind, code, value = match.groups()
    number = int(value, 16)
    if number >= 1 << 31:  # tracking id -1 is printed as ffffffff
        number -= 1 << 32
    return RawEvent(int(sec) + int(usec) / 10 ** len(usec), int(kind, 16), int(code, 16), number)


@dataclass
class Gesture:
    """First finger's path, in device time and raw panel units."""

    points: list[tuple[float, int, int]]
    fingers: int = 1
    complete: bool = True  # False if the position of the first finger was never reported

    @property
    def start(self) -> float:
        return self.points[0][0]

    @property
    def end(self) -> float:
        return self.points[-1][0]


@dataclass
class GestureParser:
    """Feed parsed events; `push` returns a gesture once every finger has lifted."""

    _slot: int = 0
    # Protocol B: per-slot tracking id and last reported position. The kernel suppresses
    # unchanged values, so a new touch at the same x as the previous one may only report y.
    _slots: dict[int, dict[str, int | None]] = field(default_factory=dict)
    _pending: dict[int, dict[str, int]] = field(default_factory=dict)
    # Protocol A: the contact being described and the contacts closed so far in this frame.
    _contact: dict[str, int] = field(default_factory=dict)
    _contacts: list[dict[str, int]] = field(default_factory=list)
    _protocol_a: bool = False
    _mt_report: bool = False
    _touch_up: bool = False
    # Contacts after the previous SYN_REPORT: id -> (x, y), None while unknown.
    _current: dict[int, tuple[int | None, int | None]] = field(default_factory=dict)
    _primary: int | None = None
    _points: list[tuple[float, int, int]] = field(default_factory=list)
    _fingers: int = 0
    _complete: bool = True
    _primary_up: bool = False

    @property
    def touching_since(self) -> float | None:
        """Device time of the current gesture's touch-down, while a finger is down."""
        return self._points[0][0] if self._primary is not None and self._points else None

    def push(self, event: RawEvent) -> Gesture | None:
        if event.type == EV_ABS:
            if event.code == ABS_MT_SLOT:
                self._slot = event.value
            elif event.code in _KEYS:
                self._pending.setdefault(self._slot, {})[_KEYS[event.code]] = event.value
                self._contact[_KEYS[event.code]] = event.value
        elif event.type == EV_KEY and event.code == BTN_TOUCH and event.value == 0:
            self._touch_up = True
        elif event.type == EV_SYN and event.code == SYN_MT_REPORT:
            self._protocol_a = self._mt_report = True
            if "x" in self._contact and "y" in self._contact:
                self._contacts.append(self._contact)
            self._contact = {}
        elif event.type == EV_SYN and event.code == SYN_REPORT:
            return self._advance(event.time, self._contacts_now())
        return None

    def _contacts_now(self) -> dict[int, tuple[int | None, int | None]]:
        pending, contacts, touch_up, mt_report = (
            self._pending,
            self._contacts,
            self._touch_up,
            self._mt_report,
        )
        self._pending, self._contact, self._contacts = {}, {}, []
        self._touch_up = self._mt_report = False
        if self._protocol_a:
            if touch_up:
                return {}
            if not mt_report:  # nothing about contacts in this frame
                return dict(self._current)
            return {c.get("id", i): (c["x"], c["y"]) for i, c in enumerate(contacts)}
        for slot, change in pending.items():
            state = self._slots.setdefault(slot, {"id": None, "x": None, "y": None})
            state.update({k: v for k, v in change.items() if k in ("x", "y")})
            if "id" in change:
                state["id"] = change["id"] if change["id"] >= 0 else None
        if touch_up:
            for state in self._slots.values():
                state["id"] = None
        return {slot: (s["x"], s["y"]) for slot, s in self._slots.items() if s["id"] is not None}

    def _advance(self, t: float, current: dict[int, tuple[int | None, int | None]]) -> Gesture | None:
        previous, self._current = self._current, current
        if self._primary is None:
            started = [c for c in current if c not in previous]
            if not started or previous:
                return None  # nothing new, or a finger was already down when recording started
            self._primary = min(started)
            self._points, self._fingers, self._complete, self._primary_up = [], 0, True, False
        self._fingers = max(self._fingers, len(current))
        if not self._primary_up:
            if self._primary in current:
                x, y = current[self._primary]
                if x is None or y is None:
                    self._complete = False
                elif not self._points or self._points[-1][1:] != (x, y):
                    self._points.append((t, x, y))
            else:
                if self._points:
                    self._points.append((t, *self._points[-1][1:]))
                self._primary_up = True
        if current:
            return None
        gesture = Gesture(self._points, self._fingers, self._complete and bool(self._points))
        self._primary = None
        return gesture

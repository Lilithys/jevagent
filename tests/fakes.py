"""A simulated phone for tests: synthetic game screens, loading delays and a fake clock."""

from __future__ import annotations

import cv2
import numpy as np

W, H = 2376, 1152  # the HONOR's landscape screenshot size

# name -> (x, y, w, h, colour, text); a few distinct "buttons" per screen
BUTTONS = {
    "home": [(2120, 150, 140, 120, (40, 160, 230), "SHOP"), (60, 980, 160, 120, (90, 200, 90), "BAG")],
    "shop": [
        (180, 980, 150, 120, (200, 120, 40), "TAB"),
        (520, 300, 260, 300, (60, 60, 200), "GIFT"),
        (40, 40, 160, 90, (180, 180, 180), "BACK"),
    ],
    "popup": [(1000, 700, 380, 120, (30, 200, 220), "OK")],
}

# home --SHOP--> shop --GIFT--> popup --OK--> shop --BACK--> home: (screen, button) -> (next, loading s)
ROUTES = {
    ("home", 0): ("shop", 2.0),
    ("shop", 1): ("popup", 0.8),
    ("popup", 0): ("shop", 0.5),
    ("shop", 2): ("home", 1.0),
}
PLAN = [("home", 0, 3.0), ("shop", 1, 2.5), ("popup", 0, 1.2), ("shop", 2, 1.0)]  # (screen, button, gap)


def make_screen(name: str, seed: int, shift: tuple[int, int] = (0, 0)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 90, size=(H // 8, W // 8, 3), dtype=np.uint8)
    image = cv2.resize(image, (W, H), interpolation=cv2.INTER_CUBIC)  # blotchy "scenery"
    for x, y, w, h, colour, text in BUTTONS.get(name, []):
        x, y = x + shift[0], y + shift[1]
        cv2.rectangle(image, (x, y), (x + w, y + h), colour, -1)
        cv2.rectangle(image, (x + 6, y + 6), (x + w - 6, y + h - 6), (255, 255, 255), 4)
        cv2.putText(image, text, (x + 18, y + h // 2 + 14), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (20, 20, 20), 4)
    return image


def centre(name: str, index: int, shift: tuple[int, int] = (0, 0)) -> tuple[float, float]:
    x, y, w, h, *_ = BUTTONS[name][index]
    return x + w / 2 + shift[0], y + h / 2 + shift[1]


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 0)


class FakePhone:
    """frame() costs 0.12 s of fake time and shows a moving 'character' over the scenery.

    `routes` maps (screen, button index) -> (next screen, loading seconds); a gesture that
    starts inside that button switches screens after the loading time.
    """

    def __init__(
        self,
        screens: dict[str, np.ndarray],
        start: str,
        clock: FakeClock,
        routes: dict[tuple[str, int], tuple[str, float]] | None = None,
        shifts: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        self.screens, self.screen, self.clock = screens, start, clock
        self.routes = routes or {}
        self.shifts = shifts or {}
        self.size = (W, H)
        self.gestures: list[list[list[float]]] = []
        self._pending: tuple[float, str] | None = None
        self.serial = "FAKE"

    def _settle(self) -> None:
        if self._pending and self.clock.now >= self._pending[0]:
            self.screen, self._pending = self._pending[1], None

    def frame(self) -> np.ndarray:
        self.clock.sleep(0.12)
        self._settle()
        image = self.screens[self.screen].copy()
        x = int(1300 + 300 * np.sin(self.clock.now))  # animated figure away from the buttons
        cv2.circle(image, (x, 520), 90, (220, 220, 250), -1)
        return image

    def gesture(self, points, stop=None) -> None:
        self._settle()
        self.gestures.append([list(p) for p in points])
        x, y = points[0][1:]
        for (screen, index), (target, loading) in self.routes.items():
            if screen != self.screen:
                continue
            bx, by, bw, bh, *_ = BUTTONS[screen][index]
            dx, dy = self.shifts.get(screen, (0, 0))
            if bx + dx <= x <= bx + dx + bw and by + dy <= y <= by + dy + bh:
                self._pending = (self.clock.now + points[-1][0] + loading, target)
        self.clock.sleep(points[-1][0])

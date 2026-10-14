import threading

import cv2
import pytest
from fakes import BUTTONS, ROUTES, FakeClock, FakePhone, centre, make_screen

from jevagent.flow import Flow, Step, save
from jevagent.routine import run_routine


class ChestPhone(FakePhone):
    """The shop offers a limited number of GIFTs (like full chests); then GIFT disappears."""

    def __init__(self, *args, gifts: int = 2, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.gifts = gifts
        x, y, w, h, *_ = BUTTONS["shop"][1]
        self.empty_shop = self.screens["shop"].copy()
        self.empty_shop[y - 10 : y + h + 10, x - 10 : x + w + 10] = self.empty_shop[
            700 : 720 + h, 1500 : 1520 + w
        ]
        self.screens = {**self.screens}
        if gifts == 0:
            self.screens["shop"] = self.empty_shop

    def gesture(self, points, stop=None) -> None:
        on_gift = self.screen == "shop" and self.gifts > 0 and _inside(points[0][1:], BUTTONS["shop"][1])
        super().gesture(points, stop)
        if on_gift:
            self.gifts -= 1
            if self.gifts == 0:
                self.screens["shop"] = self.empty_shop


def _inside(point, button):
    x, y, w, h, *_ = button
    return x <= point[0] <= x + w and y <= point[1] <= y + h


def make_flow(folder, name, plan, end):
    """plan: [(screen, button)]; images are the clean recorded screens."""
    folder.mkdir(parents=True)
    screens = {
        "home": make_screen("home", 1),
        "shop": make_screen("shop", 2),
        "popup": make_screen("popup", 3),
    }
    steps = []
    for i, (screen, button) in enumerate(plan):
        x, y = centre(screen, button)
        cv2.imwrite(str(folder / f"step-{i + 1:02d}.jpg"), screens[screen])
        steps.append(Step(points=[[0.0, x, y], [0.1, x, y]], gap=2.0, image=f"step-{i + 1:02d}.jpg"))
    cv2.imwrite(str(folder / "end.jpg"), screens[end])
    flow = Flow(name=name, size=[2376, 1152], steps=steps, end_image="end.jpg", end_gap=3.0)
    save(flow, folder)
    return folder


@pytest.fixture
def segments(tmp_path):
    return [
        make_flow(tmp_path / "A", "A", [("home", 0)], "shop"),  # open the shop
        make_flow(tmp_path / "B", "B", [("shop", 1), ("popup", 0)], "shop"),  # take one gift
        make_flow(tmp_path / "C", "C", [("shop", 2)], "home"),  # back home
    ]


def run(segments, phone, clock, rounds, stop=None):
    return run_routine(
        phone, segments, {"B"}, rounds, stop=stop, log=lambda s: None, clock=clock, sleep=clock.sleep
    )


def test_repeats_a_flow_until_its_start_screen_is_gone(segments):
    screens = {
        "home": make_screen("home", 1),
        "shop": make_screen("shop", 2),
        "popup": make_screen("popup", 3),
    }
    clock = FakeClock()
    phone = ChestPhone(screens, "home", clock, ROUTES, gifts=3)
    status, reason, done = run(segments, phone, clock, rounds=2)
    assert status == "success", reason
    assert [(s.round, s.flow) for s in done] == [
        (1, "A"),
        (1, "B"),
        (1, "B"),
        (1, "B"),
        (1, "C"),
        (2, "A"),
        (2, "C"),
    ]
    assert len(phone.gestures) == 1 + 3 * 2 + 1 + 1 + 1
    assert not list((segments[1] / "runs").glob("*/run.json"))[
        3:
    ]  # "nothing left" is not recorded as a failed run


def test_a_failing_flow_stops_the_routine(segments):
    screens = {
        "home": make_screen("home", 1),
        "shop": make_screen("shop", 2),
        "popup": make_screen("popup", 3),
    }
    clock = FakeClock()
    routes = {k: v for k, v in ROUTES.items() if k != ("shop", 2)}  # BACK does nothing
    phone = ChestPhone(screens, "home", clock, routes, gifts=1)
    status, reason, done = run(segments, phone, clock, rounds=3)
    assert status == "failed" and "第 1 轮「C」" in reason
    assert [s.flow for s in done] == ["A", "B", "C"]


def test_stop_request_ends_the_routine(segments):
    screens = {
        "home": make_screen("home", 1),
        "shop": make_screen("shop", 2),
        "popup": make_screen("popup", 3),
    }
    clock = FakeClock()
    stop = threading.Event()
    phone = ChestPhone(screens, "home", clock, ROUTES, gifts=5)

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.now > 1012:
            stop.set()

    status, _, done = run_routine(
        phone, segments, {"B"}, 2, stop=stop, log=lambda s: None, clock=clock, sleep=sleep
    )
    assert status == "stopped" and 0 < len(done) < 8

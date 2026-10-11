import json
import threading

import cv2
import pytest
from fakes import PLAN, ROUTES, FakeClock, FakePhone, centre, make_screen

from jevagent.player import Player, load_runs, new_run_dir


def play(flow, folder, phone, clock, **kwargs):
    player = Player(phone, flow, folder, clock=clock, sleep=clock.sleep, log=lambda s: None, **kwargs)
    run_dir = new_run_dir(folder)
    return player.run(run_dir), run_dir


def test_replays_whole_flow_and_confirms_end_screen(recorded, screens):
    flow, folder = recorded
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES)
    result, run_dir = play(flow, folder, phone, clock)
    assert result.status == "success", result.reason
    assert [g[0][1:] for g in phone.gestures] == [list(centre(s, b)) for s, b, _ in PLAN]
    assert all(s.score > 0.9 for s in result.steps)
    assert result.steps[1].waited >= 2.0  # waited for the shop to load instead of a fixed timer
    assert result.end_score >= 0.6
    saved = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert saved["status"] == "success" and (run_dir / "last.jpg").is_file()
    assert [d for d, _ in load_runs(folder)] == [run_dir]


def test_slow_loading_is_waited_out(recorded, screens):
    flow, folder = recorded
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, {**ROUTES, ("home", 0): ("shop", 8.0)})
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success"
    assert result.steps[1].waited >= 8.0


def test_gesture_follows_a_moved_button(recorded, screens):
    flow, folder = recorded
    clock = FakeClock()
    moved = {**screens, "shop": make_screen("shop", 2, shift=(40, 25))}
    phone = FakePhone(moved, "home", clock, ROUTES, shifts={"shop": (40, 25)})
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success"
    x, y = centre("shop", 1)
    assert phone.gestures[1][0][1:] == pytest.approx([x + 40, y + 25], abs=2.5)


def test_stops_without_touching_when_the_expected_screen_never_appears(recorded, screens):
    flow, folder = recorded
    clock = FakeClock()
    routes = {k: v for k, v in ROUTES.items() if k != ("home", 0)}  # the shop never opens
    phone = FakePhone(screens, "home", clock, routes)
    result, run_dir = play(flow, folder, phone, clock)
    assert result.status == "failed" and "第 2 步" in result.reason
    assert len(phone.gestures) == 1
    assert result.steps[-1].status == "failed" and result.steps[-1].score < 0.8
    assert (run_dir / "last.jpg").is_file()


def test_wrong_start_screen_sends_nothing(recorded, screens):
    flow, folder = recorded
    clock = FakeClock()
    phone = FakePhone(screens, "shop", clock, ROUTES)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "failed" and "第 1 步" in result.reason
    assert phone.gestures == []
    assert clock.now - 1000 < 7  # first step only waits a few seconds


def test_unchecked_first_step_still_requires_the_start_screen(recorded, screens):
    flow, folder = recorded
    flow.steps[0].check = False
    clock = FakeClock()
    result, _ = play(flow, folder, FakePhone(screens, "popup", clock, ROUTES), clock)
    assert result.status == "failed" and "录制起点" in result.reason
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES)
    assert play(flow, folder, phone, clock)[0].status == "success"


def test_unchecked_step_keeps_the_recorded_rhythm(recorded, screens):
    flow, folder = recorded
    flow.steps[2].check = False  # popup's OK; recorded 1.2 s after the previous tap
    clock = FakeClock()
    result, _ = play(flow, folder, FakePhone(screens, "home", clock, ROUTES), clock)
    assert result.status == "success"
    assert result.steps[2].waited == pytest.approx(1.2, abs=0.01)
    assert result.steps[2].score is None


def test_end_screen_mismatch_is_a_failure(recorded, screens):
    flow, folder = recorded
    cv2.imwrite(str(folder / "end.jpg"), screens["popup"])
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "failed" and "最终画面" in result.reason
    assert len(phone.gestures) == 4
    flow.end_check = False
    clock = FakeClock()
    assert play(flow, folder, FakePhone(screens, "home", clock, ROUTES), clock)[0].status == "success"


def test_stop_request_ends_the_run(recorded, screens):
    flow, folder = recorded
    clock = FakeClock()
    stop = threading.Event()

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.now > 1003:
            stop.set()

    phone = FakePhone(screens, "home", clock, ROUTES)
    player = Player(phone, flow, folder, clock=clock, sleep=sleep, stop=stop, log=lambda s: None)
    result = player.run(new_run_dir(folder))
    assert result.status == "stopped"
    assert len(phone.gestures) < 4


def test_refuses_a_screen_with_a_different_shape(recorded, screens):
    flow, folder = recorded
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES)
    phone.size = (1152, 2376)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "error" and phone.gestures == []

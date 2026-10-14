import json
import threading

import cv2
import numpy as np
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


def test_tap_anywhere_step_taps_again_until_the_next_screen(recorded, screens):
    flow, folder = recorded
    flow.steps[2].check, flow.steps[2].until_next = False, True  # the popup's OK as "tap anywhere"
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES, ignore={"popup": 2})  # first two taps swallowed
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success", result.reason
    assert result.steps[2].taps == 3 and len(phone.gestures) == 6
    assert result.steps[2].waited == pytest.approx(1.2, abs=0.01)  # min(gap, 1.5): no long blind wait


def test_tap_anywhere_step_gives_up_after_five_taps(recorded, screens):
    flow, folder = recorded
    flow.steps[2].check, flow.steps[2].until_next = False, True
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES, ignore={"popup": 99})
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "failed" and "点了 5 次" in result.reason
    assert result.steps[2].taps == 5 and len(phone.gestures) == 2 + 5


def test_last_step_tap_anywhere_waits_for_the_end_screen(recorded, screens):
    flow, folder = recorded
    flow.steps[3].check, flow.steps[3].until_next = False, True  # BACK as the last, unchecked step
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES, ignore={"shop": 0})
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success" and result.steps[3].taps == 1


def test_checked_tap_until_next_retaps_only_while_its_screen_is_still_there(recorded, screens):
    flow, folder = recorded
    flow.steps[2].until_next = True  # checked OK button + tap until the shop shows
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES, ignore={"popup": 1})  # first tap swallowed
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success" and result.steps[2].taps == 2

    clock = FakeClock()
    unexpected = {**ROUTES, ("popup", 0): ("home", 0.3)}  # OK leads somewhere the flow did not expect
    phone = FakePhone(screens, "home", clock, unexpected)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "failed" and "下一画面仍未出现" in result.reason
    assert result.steps[2].taps == 1  # popup gone: no more taps on the wrong screen


def test_step_can_check_one_spot_and_tap_another(recorded, screens):
    flow, folder = recorded
    # Check the shop's BACK button, still tap GIFT. (Not TAB: in these synthetic screens it looks like
    # the home screen's BAG button nearby, so it would match before the shop opens.)
    flow.steps[1].look = list(centre("shop", 2))
    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success"
    assert phone.gestures[1][0][1:] == list(centre("shop", 1))

    no_back = screens["shop"].copy()
    no_back[30:140, 30:210] = no_back[400:510, 1700:1880]  # the checked button is missing this time
    clock = FakeClock()
    phone = FakePhone({**screens, "shop": no_back}, "home", clock, ROUTES)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "failed" and "第 2 步" in result.reason and len(phone.gestures) == 1


def test_end_can_be_confirmed_by_one_spot(recorded, screens):
    flow, folder = recorded
    reframed = screens["popup"].copy()  # the "map" is framed differently this visit...
    reframed[80:340, 2040:2376] = screens["home"][80:340, 2040:2376]  # ...but the SHOP button is unchanged
    flow.end_look = list(centre("home", 0))  # but the SHOP button is where it was
    clock = FakeClock()
    phone = FakePhone({**screens, "home": reframed}, "home", clock, ROUTES)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success" and result.end_score >= 0.6

    flow.end_look = None  # whole-screen comparison fails on the reframed screen
    clock = FakeClock()
    phone = FakePhone({**screens, "home": reframed}, "home", clock, ROUTES)
    assert play(flow, folder, phone, clock)[0].status == "failed"


class BattlePhone(FakePhone):
    """Shows a chaotic 'battle' screen; the expected screen flashes up for `flash` frames at 30 s."""

    def __init__(self, *args, flash: int, target: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.flash, self.target, self.frames = flash, target, 0

    def frame(self):
        image = super().frame()
        if self.clock.now - 1000 >= 30 and self.flash > 0:
            self.flash -= 1
            return self.screens[self.target].copy()
        rng = np.random.default_rng(int(self.clock.now * 1000))
        return rng.integers(0, 255, image.shape, dtype=np.uint8)


def test_after_a_long_wait_a_brief_look_alike_is_not_enough(recorded, screens):
    flow, folder = recorded
    flow.steps = flow.steps[:1]  # tap SHOP, after waiting through a long battle
    flow.steps[0].timeout = 60
    flow.end_check = False
    for flash, expected in ((2, "failed"), (3, "success")):
        clock = FakeClock()
        phone = BattlePhone(screens, "home", clock, flash=flash, target="home")
        result, _ = play(flow, folder, phone, clock)
        assert result.status == expected, (flash, result.reason)


def test_resume_from_a_later_step(recorded, screens):
    flow, folder = recorded
    clock = FakeClock()
    phone = FakePhone(screens, "shop", clock, ROUTES)  # step 1 already done by hand
    player = Player(phone, flow, folder, clock=clock, sleep=clock.sleep, log=lambda s: None, start=2)
    result = player.run(new_run_dir(folder))
    assert result.status == "success" and [s.step for s in result.steps] == [2, 3, 4]
    assert len(phone.gestures) == 3


def test_optional_step_is_done_when_its_screen_appears_and_skipped_otherwise(recorded, screens):
    flow, folder = recorded
    flow.steps[2].optional = True  # the popup's OK: only some rounds show the popup

    clock = FakeClock()
    phone = FakePhone(screens, "home", clock, ROUTES)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success" and [s.status for s in result.steps] == ["done"] * 4

    clock = FakeClock()
    no_popup = {k: v for k, v in ROUTES.items() if k != ("shop", 1)}  # GIFT shows no popup this time
    phone = FakePhone(screens, "home", clock, no_popup)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "success", result.reason
    assert [s.status for s in result.steps] == ["done", "done", "skipped", "done"]
    assert len(phone.gestures) == 3  # nothing was tapped for the skipped step
    assert result.steps[2].waited >= 3.0  # the next screen had to stay for SKIP_SETTLE first


def test_optional_step_still_fails_when_neither_screen_appears(recorded, screens):
    flow, folder = recorded
    flow.steps[2].optional = True
    clock = FakeClock()
    routes = {**ROUTES, ("shop", 1): ("home", 0.5)}  # GIFT leads somewhere unexpected
    phone = FakePhone(screens, "home", clock, routes)
    result, _ = play(flow, folder, phone, clock)
    assert result.status == "failed" and "第 3 步" in result.reason

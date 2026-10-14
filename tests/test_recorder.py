import numpy as np
import pytest
from fakes import FakeClock, centre, make_screen
from test_touch import down, move, up

from jevagent.flow import load, save
from jevagent.recorder import FrameBuffer, Recorder, screen_points
from jevagent.touch import Gesture, TouchScreen, up_to_natural
from jevagent.vision import screen_similarity

NATURAL = (1152, 2376)  # portrait display; the game runs in landscape (rotation 1)
SCREEN = TouchScreen("/dev/input/event5", "ts", (0, 1151), (0, 2375))  # 1 raw unit = 1 pixel
OFFSET = 50.0  # host clock - device clock


def raw(x, y):
    """Raw touch coordinates for a landscape screenshot pixel."""
    rx, ry = up_to_natural((x, y), NATURAL, 1)
    return round(rx), round(ry)


def test_screen_points_maps_rotation_and_collapses_taps():
    x, y = 2190.0, 211.0
    tap = Gesture([(5.0, *raw(x, y)), (5.08, *raw(x + 3, y + 2)), (5.15, *raw(x + 4, y))])
    assert screen_points(tap, SCREEN, NATURAL, 1, (2376, 1152)) == [[0.0, x, y], [0.15, x, y]]
    swipe = Gesture(
        [(1.0, *raw(1000, 600)), (1.004, *raw(1010, 600)), (1.05, *raw(1300, 600)), (1.2, *raw(1600, 610))]
    )
    points = screen_points(swipe, SCREEN, NATURAL, 1, (2376, 1152))
    assert points == [[0.0, 1000.0, 600.0], [0.05, 1300.0, 600.0], [0.2, 1600.0, 610.0]]


def test_frame_buffer_returns_newest_frame_before_a_time():
    buffer = FrameBuffer(maxlen=3)
    for t in (1.0, 2.0, 3.0, 4.0):
        buffer.add(t, np.full((2, 2, 3), t, np.uint8))
    assert buffer.before(3.5)[0] == 3.0
    assert buffer.before(0.5)[0] == 2.0  # oldest kept when nothing is older


class FakeProc:
    def __init__(self, lines, clock):
        self.lines, self.clock = lines, clock

    @property
    def stdout(self):
        for text in self.lines:
            self.clock.now = float(text[1:].split("]")[0]) + OFFSET + 0.02  # arrives 20 ms later
            yield text

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


class FakeRecordingPhone:
    def __init__(self, end_frame):
        self.end_frame = end_frame
        self.size = (2376, 1152)
        self.serial = "FAKE"

    def frame(self):
        return self.end_frame


def test_records_steps_with_the_screen_seen_before_each_touch(tmp_path):
    home, shop = make_screen("home", 1), make_screen("shop", 2)
    flat = np.full((1152, 2376, 3), 35, np.uint8)
    clock = FakeClock()
    recorder = Recorder(FakeRecordingPhone(home), tmp_path, log=lambda s: None, clock=clock)
    recorder.screen, recorder.natural, recorder.orientation, recorder.size = SCREEN, NATURAL, 1, (2376, 1152)
    recorder.started = OFFSET + 48.0
    for t, frame in ((49.0, home), (50.5, home), (51.3, shop), (53.2, flat)):
        recorder.frames.add(t + OFFSET, frame)

    shop_btn, gift, tab = raw(*centre("home", 0)), raw(*centre("shop", 1)), raw(*centre("shop", 0))
    lines = (
        down(51.0, *shop_btn)
        + up(51.1)  # 1: tap SHOP on home
        + down(52.5, *gift)
        + up(52.6)  # 2: tap GIFT once the shop is showing
        + down(52.9, *tab, tid=9)
        + up(53.0)  # 3: quick follow-up 0.3 s later
        + down(54.0, 100, 100, tid=10)
        + down(54.05, 900, 900, slot=1, tid=11)
        + up(54.1, slot=1)
        + up(54.2)
        + down(55.0, *raw(1500, 900), tid=12)
        + move(55.2, *raw(1700, 900))
        + up(55.4)  # 4: swipe on flat
    )
    recorder._proc = FakeProc(lines, clock)
    recorder._read_events()

    assert len((tmp_path / "getevent.log").read_text(encoding="utf-8").splitlines()) == len(lines)
    assert recorder.skipped == 1  # the two-finger gesture
    steps = recorder.steps
    assert [s.kind for s in steps] == ["tap", "tap", "tap", "swipe"]
    assert steps[0].points[0][1:] == pytest.approx(list(centre("home", 0)), abs=1)
    assert [s.gap for s in steps] == pytest.approx([3.02, 1.4, 0.3, 2.0], abs=0.01)
    assert [s.check for s in steps] == [True, True, False, False]
    assert "0.3s" in steps[2].note and "空白处" in steps[3].note
    assert [s.until_next for s in steps] == [False, False, False, True]  # quick follow-ups keep their rhythm

    def image(i):
        import cv2

        return cv2.imread(str(tmp_path / steps[i].image))

    assert screen_similarity(image(0), home) > 0.9  # frame from before the tap, not after
    assert screen_similarity(image(1), shop) > 0.9

    clock.now += 3.0  # you look at the result, then press Enter
    flow = recorder.finish("demo")
    assert flow.end_image == "end.jpg" and flow.end_check
    assert flow.end_gap == pytest.approx(3.0, abs=0.01)
    save(flow, tmp_path)
    assert load(tmp_path).steps == steps

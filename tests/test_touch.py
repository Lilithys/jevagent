import random

import pytest

from jevagent.touch import (
    GestureParser,
    TouchScreen,
    natural_to_up,
    parse_event,
    parse_input_devices,
    pick_touchscreen,
    up_to_natural,
)

GETEVENT_P = """add device 1: /dev/input/event1
  name:     "gpio-keys"
  events:
    KEY (0001): 0072  0073  0074
  input props:
    <none>
add device 2: /dev/input/event5
  name:     "huawei,touchscreen"
  events:
    KEY (0001): 008f  014a
    ABS (0003): 002f  : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0
                0030  : value 0, min 0, max 255, fuzz 0, flat 0, resolution 0
                0035  : value 0, min 0, max 1343, fuzz 0, flat 0, resolution 0
                0036  : value 0, min 0, max 2771, fuzz 0, flat 0, resolution 0
                0039  : value 0, min 0, max 65535, fuzz 0, flat 0, resolution 0
  input props:
    INPUT_PROP_DIRECT
"""


def line(t: float, kind: int, code: int, value: int) -> str:
    sec, usec = divmod(round(t * 1_000_000), 1_000_000)
    return f"[{sec:8d}.{usec:06d}] {kind:04x} {code:04x} {value & 0xFFFFFFFF:08x}"


def down(t, x, y, slot=0, tid=7):
    return [
        line(t, 3, 0x2F, slot),
        line(t, 3, 0x39, tid),
        line(t, 3, 0x35, x),
        line(t, 3, 0x36, y),
        line(t, 1, 0x14A, 1),
        line(t, 0, 0, 0),
    ]


def move(t, x, y, slot=0):
    return [line(t, 3, 0x2F, slot), line(t, 3, 0x35, x), line(t, 3, 0x36, y), line(t, 0, 0, 0)]


def up(t, slot=0):
    return [line(t, 3, 0x2F, slot), line(t, 3, 0x39, -1), line(t, 1, 0x14A, 0), line(t, 0, 0, 0)]


def feed(lines):
    parser, gestures = GestureParser(), []
    for text in lines:
        event = parse_event(text)
        if event is not None:
            gesture = parser.push(event)
            if gesture is not None:
                gestures.append(gesture)
    return gestures


def test_finds_touchscreen_among_input_devices():
    screens = parse_input_devices(GETEVENT_P)
    assert screens == [TouchScreen("/dev/input/event5", "huawei,touchscreen", (0, 1343), (0, 2771), True)]
    assert pick_touchscreen(screens) == screens[0]
    assert pick_touchscreen([]) is None


def test_parses_event_lines_including_negative_tracking_id():
    assert parse_event("[   20517.358413] 0003 0035 0000021e").value == 0x21E
    assert parse_event("[   20517.358413] 0003 0039 ffffffff").value == -1
    assert parse_event("[    5.000100] /dev/input/event5: 0003 0036 00000010\r\n").time == pytest.approx(
        5.0001
    )
    assert parse_event("add device 1: /dev/input/event5") is None


def test_tap_and_long_press():
    gestures = feed(down(10.0, 600, 1200) + up(10.12) + down(12.0, 700, 900, tid=8) + up(13.0))
    assert [g.points for g in gestures] == [
        [(10.0, 600, 1200), (10.12, 600, 1200)],
        [(12.0, 700, 900), (13.0, 700, 900)],
    ]
    assert all(g.fingers == 1 and g.complete for g in gestures)


def test_swipe_keeps_path_and_timing():
    (gesture,) = feed(down(1.0, 100, 100) + move(1.05, 150, 100) + move(1.10, 220, 110) + up(1.2))
    assert gesture.points == [(1.0, 100, 100), (1.05, 150, 100), (1.10, 220, 110), (1.2, 220, 110)]


def test_second_touch_keeps_coordinate_the_kernel_did_not_repeat():
    # Same x as the first tap: the kernel only reports tracking id and y.
    second = [line(3.0, 3, 0x39, 9), line(3.0, 3, 0x36, 1500), line(3.0, 0, 0, 0)] + up(3.1)
    gestures = feed(down(2.0, 600, 1200) + up(2.1) + second)
    assert gestures[1].points[0] == (3.0, 600, 1500)


def test_two_fingers_are_flagged():
    events = down(1.0, 100, 100) + down(1.1, 900, 900, slot=1, tid=8) + up(1.3, slot=1) + up(1.4)
    (gesture,) = feed(events)
    assert gesture.fingers == 2


def test_finger_already_down_when_recording_starts_is_ignored():
    gestures = feed(move(1.0, 300, 300) + up(1.1) + down(2.0, 50, 60) + up(2.1))
    assert len(gestures) == 1 and gestures[0].points[0] == (2.0, 50, 60)


def test_touching_since_is_set_only_during_a_gesture():
    parser = GestureParser()
    for text in down(4.0, 10, 20):
        parser.push(parse_event(text))
    assert parser.touching_since == 4.0
    for text in up(4.1):
        parser.push(parse_event(text))
    assert parser.touching_since is None


@pytest.mark.parametrize("orientation", [0, 1, 2, 3])
def test_orientation_transforms_match_airtest(orientation):
    from airtest.core.android.rotation import XYTransformer

    natural = (1152, 2376)
    rng = random.Random(orientation)
    for _ in range(20):
        point = (rng.uniform(0, 2376), rng.uniform(0, 1152))
        assert up_to_natural(point, natural, orientation) == XYTransformer.up_2_ori(
            point, natural, orientation
        )
        assert natural_to_up(
            up_to_natural(point, natural, orientation), natural, orientation
        ) == pytest.approx(point)


def test_raw_units_scale_to_display_pixels():
    screen = TouchScreen("/dev/input/event5", "ts", (0, 1343), (0, 2771))
    assert screen.to_natural(672, 1386, (1152, 2376)) == pytest.approx((576.0, 1188.0), abs=0.5)


# `adb shell getevent -p` on the HONOR ELZ_AN00 (Android 14), trimmed to the touch-related devices.
# Note: no 002f (ABS_MT_SLOT) -> multi-touch protocol A.
HONOR_GETEVENT_P = """add device 3: /dev/input/event6
  name:     "input_mt_wrapper"
  events:
    KEY (0001): 003b  0072  0073  0074  00c4  00c5  00fb  0145
                014a  0264  02c1  02c2
    ABS (0003): 0000  : value 0, min 0, max 1343, fuzz 0, flat 0, resolution 0
                0001  : value 0, min 0, max 2771, fuzz 0, flat 0, resolution 0
                0018  : value 0, min 0, max 100, fuzz 0, flat 0, resolution 0
                001d  : value 0, min 0, max 32767, fuzz 0, flat 0, resolution 0
                0030  : value 0, min 0, max 1, fuzz 0, flat 0, resolution 0
                0031  : value 0, min 0, max 1, fuzz 0, flat 0, resolution 0
                0034  : value 0, min -90, max 90, fuzz 0, flat 0, resolution 0
                0035  : value 0, min 0, max 10751, fuzz 0, flat 0, resolution 0
                0036  : value 0, min 0, max 22175, fuzz 0, flat 0, resolution 0
                0038  : value 0, min 0, max 10, fuzz 0, flat 0, resolution 0
                0039  : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0
                003a  : value 0, min 0, max 100, fuzz 0, flat 0, resolution 0
  input props:
    INPUT_PROP_DIRECT
add device 7: /dev/input/event3
  name:     "STM VL53L1 proximity sensor"
  events:
    ABS (0003): 0006  : value 0, min 0, max -1, fuzz 0, flat 0, resolution 0
                0019  : value 0, min 0, max 255, fuzz 0, flat 0, resolution 0
  input props:
    <none>
"""


def frame_a(t, contacts, touch=None):
    """One protocol-A frame: each contact closed by SYN_MT_REPORT, then SYN_REPORT."""
    lines = []
    for contact in contacts:
        if "id" in contact:
            lines.append(line(t, 3, 0x39, contact["id"]))
        lines += [
            line(t, 3, 0x35, contact["x"]),
            line(t, 3, 0x36, contact["y"]),
            line(t, 3, 0x3A, 40),
            line(t, 0, 2, 0),
        ]
    if not contacts:
        lines.append(line(t, 0, 2, 0))  # empty contact list
    if touch is not None:
        lines.append(line(t, 1, 0x14A, touch))
    return lines + [line(t, 0, 0, 0)]


def test_honor_touchscreen_uses_protocol_a():
    (screen,) = parse_input_devices(HONOR_GETEVENT_P)
    assert screen == TouchScreen("/dev/input/event6", "input_mt_wrapper", (0, 10751), (0, 22175), True, False)
    assert screen.protocol.startswith("A")
    assert parse_input_devices(GETEVENT_P)[0].protocol.startswith("B")


def test_honor_raw_units_match_android_scale():
    # dumpsys input: RawToDisplay scale 0.1071 = 1152 / 10752 (8 raw units per panel pixel).
    (screen,) = parse_input_devices(HONOR_GETEVENT_P)
    assert screen.to_natural(10752 // 2, 22176 // 2, (1152, 2376)) == pytest.approx((576, 1188))
    assert screen.to_natural(1000, 1000, (1152, 2376)) == pytest.approx(
        (1000 * 0.10714, 1000 * 0.10714), abs=0.01
    )


def test_protocol_a_tap_swipe_and_lift_styles():
    events = (
        frame_a(1.0, [{"id": 0, "x": 5000, "y": 9000}], touch=1)
        + frame_a(1.008, [{"id": 0, "x": 5000, "y": 9000}])  # positions are repeated every frame
        + frame_a(1.1, [])  # lift: empty contact list
        + frame_a(2.0, [{"id": 0, "x": 1000, "y": 2000}], touch=1)
        + frame_a(2.05, [{"id": 0, "x": 1600, "y": 2100}])
        + [line(2.1, 1, 0x14A, 0), line(2.1, 0, 0, 0)]  # lift: only BTN_TOUCH up
    )
    tap, swipe = feed(events)
    assert tap.points == [(1.0, 5000, 9000), (1.1, 5000, 9000)] and tap.fingers == 1 and tap.complete
    assert swipe.points == [(2.0, 1000, 2000), (2.05, 1600, 2100), (2.1, 1600, 2100)]


def test_protocol_a_frames_without_contact_info_keep_the_finger_down():
    events = (
        frame_a(1.0, [{"id": 0, "x": 100, "y": 200}], touch=1)
        + [line(1.02, 3, 0x00, 13), line(1.02, 0, 0, 0)]  # single-touch ABS_X only
        + frame_a(1.5, [])
    )
    (gesture,) = feed(events)
    assert gesture.points == [(1.0, 100, 200), (1.5, 100, 200)]


def test_protocol_a_second_finger_and_missing_ids():
    events = (
        frame_a(1.0, [{"x": 100, "y": 100}], touch=1)
        + frame_a(1.1, [{"x": 100, "y": 100}, {"x": 900, "y": 900}])
        + frame_a(1.2, [{"x": 100, "y": 100}])
        + frame_a(1.3, [], touch=0)
    )
    (gesture,) = feed(events)
    assert gesture.fingers == 2

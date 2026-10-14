import numpy as np
import pytest
from fakes import FakeClock, FakePhone, centre, make_screen

from jevagent.vision import MIN_TEXTURE, find_anchor, make_anchor, screen_similarity, to_work


def test_anchor_matches_same_screen_while_something_else_animates():
    home = make_screen("home", 1)
    phone = FakePhone({"home": home}, "home", FakeClock())
    anchor = make_anchor(home, centre("home", 0))
    for _ in range(5):
        match = find_anchor(to_work(phone.frame()), anchor)
        assert match.score > 0.95 and match.shift == (0, 0)


def test_anchor_follows_a_moved_button():
    anchor = make_anchor(make_screen("shop", 2), centre("shop", 1))
    match = find_anchor(to_work(make_screen("shop", 2, shift=(60, 30))), anchor)
    assert match.score > 0.9
    assert match.shift_in((2376, 1152)) == pytest.approx((60, 30), abs=2.5)


def test_anchor_is_not_found_on_a_different_screen():
    anchor = make_anchor(make_screen("home", 1), centre("home", 0))
    assert find_anchor(to_work(make_screen("shop", 2)), anchor).score < 0.6


def test_nearest_of_identical_buttons_wins():
    image = make_screen("none", 3)
    for x in (800, 1000):  # two identical buttons 200 px apart
        image[500:620, x : x + 120] = (40, 160, 230)
        image[530:590, x + 30 : x + 90] = (255, 255, 255)
    anchor = make_anchor(image, (860, 560))
    assert find_anchor(to_work(image), anchor).shift == (0, 0)


def test_flat_area_has_no_texture():
    flat = np.full((1152, 2376, 3), 40, np.uint8)
    assert make_anchor(flat, (1000, 500)).texture < MIN_TEXTURE
    assert make_anchor(make_screen("home", 1), centre("home", 0)).texture > MIN_TEXTURE


def test_anchor_near_the_edge_stays_inside_the_frame():
    anchor = make_anchor(make_screen("home", 1), (2375, 0))
    assert anchor.patch.shape[:2] == (58, 58)
    assert anchor.origin == (1188 - 58, 0)


def test_screen_similarity_separates_screens():
    home = make_screen("home", 1)
    phone = FakePhone({"home": home}, "home", FakeClock())
    assert screen_similarity(phone.frame(), home) >= 0.9
    assert screen_similarity(make_screen("shop", 2), home) < 0.4
    assert screen_similarity(home[:, :1000], home) == 0.0  # different shape


def test_thin_icon_is_found_when_the_page_behind_it_changes():
    """The real failure: the shop's back arrow over a different shop tab (colour match 0.58)."""
    import cv2

    from jevagent.flow import MATCH_THRESHOLD

    def page(shading: bool, icon_below: bool) -> np.ndarray:
        image = np.full((1152, 2376, 3), (190, 215, 225), np.uint8)  # beige panel
        if shading:  # soft dark scenery showing through behind the arrow
            blob = np.zeros((1152, 2376), np.float32)
            cv2.ellipse(blob, (200, 190), (160, 110), 0, 0, 360, 1.0, -1)
            blob = cv2.GaussianBlur(blob, (0, 0), 40)[..., None]
            image = (image * (1 - 0.5 * blob)).astype(np.uint8)
        if icon_below:  # another sidebar entry scrolled up under the arrow
            cv2.circle(image, (215, 205), 38, (40, 120, 210), -1)
            cv2.circle(image, (215, 205), 38, (255, 255, 255), 5)
        arrow = np.array([[230, 70], [140, 100], [230, 130], [205, 100]], np.int32)
        cv2.fillPoly(image, [arrow], (60, 180, 230))  # golden "<"
        cv2.polylines(image, [arrow], True, (30, 90, 140), 3)
        cv2.putText(image, "BACK", (245, 115), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (60, 90, 120), 3)
        return image

    recorded, replayed = page(shading=True, icon_below=False), page(shading=False, icon_below=True)
    anchor = make_anchor(recorded, (180, 112))
    match = find_anchor(to_work(replayed), anchor)
    assert match.score >= MATCH_THRESHOLD and match.shift == (0, 0)
    assert find_anchor(to_work(make_screen("home", 1)), anchor).score < MATCH_THRESHOLD

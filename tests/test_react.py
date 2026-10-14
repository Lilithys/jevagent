"""React steps on a simulated chest: normal chests go straight to the summary, gold ones
show a card board, a corridor that needs a nudge before ⏭ appears, and a legendary reveal."""

import cv2
from fakes import FakeClock, H, W, make_screen

from jevagent.flow import Flow, Step
from jevagent.player import Player, new_run_dir

OPEN = (1100, 520, 220, 130, (40, 160, 230), "OPEN")
SUM = (1050, 140, 300, 110, (90, 200, 90), "SUM")  # something only the reward summary shows
BOARD = (1780, 480, 240, 150, (200, 120, 40), "BOARD")
SKIP = (2130, 70, 140, 110, (180, 180, 180), "SKIP")
LAYOUT = {
    "panel": (10, [OPEN]),
    "summary": (11, [SUM]),
    "board": (12, [BOARD]),
    "corridor": (13, []),
    "corridor_skip": (13, [SKIP]),
    "legendary": (14, [SKIP]),
    "unknown": (15, []),
}


def draw(name):
    seed, buttons = LAYOUT[name]
    image = make_screen("none", seed)
    for x, y, w, h, colour, text in buttons:
        cv2.rectangle(image, (x, y), (x + w, y + h), colour, -1)
        cv2.rectangle(image, (x + 6, y + 6), (x + w - 6, y + h - 6), (255, 255, 255), 4)
        cv2.putText(image, text, (x + 18, y + h // 2 + 14), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (20, 20, 20), 4)
    return image


SCREENS = {name: draw(name) for name in LAYOUT}


def centre(button):
    x, y, w, h, *_ = button
    return x + w / 2, y + h / 2


def inside(point, button):
    x, y, w, h, *_ = button
    return x <= point[0] <= x + w and y <= point[1] <= y + h


class ChestGame:
    def __init__(self, clock, gold, after_open=None):
        self.clock, self.size, self.serial = clock, (W, H), "FAKE"
        self.screen, self.pending, self.gestures = "panel", None, []
        self.after_open = after_open or ("board" if gold else "summary")

    def frame(self):
        self.clock.sleep(0.12)
        if self.pending and self.clock.now >= self.pending[0]:
            self.screen, self.pending = self.pending[1], None
        return SCREENS[self.screen].copy()

    def gesture(self, points, stop=None):
        self.gestures.append((self.screen, points[0][1:], points[-1][0]))
        p = points[0][1:]
        moves = {
            ("panel", OPEN): (self.after_open, 2.5),
            ("board", BOARD): ("corridor", 1.0),
            ("corridor_skip", SKIP): ("legendary", 1.5),
            ("legendary", SKIP): ("summary", 1.0),
            ("summary", SUM): ("panel", 0.8),
        }
        if self.pending is None:  # a tap during a transition does not restart it
            for (screen, button), target in moves.items():
                if screen == self.screen and inside(p, button):
                    self.pending = (self.clock.now + target[1], target[0])
            if self.screen == "corridor":  # any tap reveals the skip button
                self.pending = (self.clock.now + 0.3, "corridor_skip")
        self.clock.sleep(points[-1][0])


def chest_flow(tmp_path):
    folder = tmp_path / "B"
    folder.mkdir()

    def step(screen, point, hold=0.1, **kw):
        image = f"{screen}.jpg"
        cv2.imwrite(str(folder / image), SCREENS[screen])
        x, y = point
        return Step(points=[[0.0, x, y], [hold, x, y]], gap=3.0, image=image, **kw)

    cv2.imwrite(str(folder / "end.jpg"), SCREENS["panel"])
    steps = [
        step("panel", centre(OPEN)),
        step("board", centre(BOARD), hold=1.0, react=True),
        step("corridor", (1889, 508), check=False, react=True),  # nudge
        step("corridor_skip", centre(SKIP), react=True),
        step("legendary", centre(SKIP), react=True),
        step("summary", centre(SUM), until_next=True),
    ]
    return Flow(name="B", size=[W, H], steps=steps, end_image="end.jpg", end_gap=3.0), folder


def play(flow, folder, game, clock):
    return Player(game, flow, folder, clock=clock, sleep=clock.sleep, log=lambda s: None).run(
        new_run_dir(folder)
    )


def test_normal_chest_skips_every_react_step(tmp_path):
    flow, folder = chest_flow(tmp_path)
    clock = FakeClock()
    game = ChestGame(clock, gold=False)
    result = play(flow, folder, game, clock)
    assert result.status == "success", result.reason
    assert [g[0] for g in game.gestures] == ["panel", "summary"]
    assert result.shots == []  # nothing to show for a normal chest


def test_gold_chest_reacts_to_board_corridor_and_skips(tmp_path):
    flow, folder = chest_flow(tmp_path)
    clock = FakeClock()
    game = ChestGame(clock, gold=True)
    result = play(flow, folder, game, clock)
    assert result.status == "success", result.reason
    assert [g[0] for g in game.gestures] == [
        "panel",
        "board",
        "corridor",
        "corridor_skip",
        "legendary",
        "summary",
    ]
    assert game.gestures[1][2] == 1.0  # the board got the recorded long press
    assert [s.step for s in result.steps] == [1, 2, 3, 4, 4, 6]  # either ⏭ step serves both skip screens
    assert result.shots == ["react-01.jpg", "react-02.jpg", "react-03.jpg", "react-04.jpg"]
    run_dir = sorted((folder / "runs").iterdir())[-1]
    assert all(
        (run_dir / shot).is_file() for shot in result.shots
    )  # the board, corridor and both skip screens


def test_no_blind_nudge_before_a_known_cutscene_screen(tmp_path):
    flow, folder = chest_flow(tmp_path)
    clock = FakeClock()
    game = ChestGame(clock, gold=False, after_open="unknown")  # opening leads somewhere unrecognised
    result = play(flow, folder, game, clock)
    assert result.status == "failed" and "应对" in result.reason
    assert [g[0] for g in game.gestures] == ["panel"]  # nothing was tapped on the unknown screen

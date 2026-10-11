import cv2
import pytest
from fakes import PLAN, centre, make_screen

from jevagent.flow import Flow, Step


@pytest.fixture
def screens():
    return {"home": make_screen("home", 1), "shop": make_screen("shop", 2), "popup": make_screen("popup", 3)}


@pytest.fixture
def recorded(tmp_path, screens):
    """A flow as the recorder would save it, demonstrated on the unshifted screens."""
    folder = tmp_path / "flow"
    folder.mkdir()
    steps = []
    for i, (screen, button, gap) in enumerate(PLAN):
        x, y = centre(screen, button)
        image = f"step-{i + 1:02d}.jpg"
        cv2.imwrite(str(folder / image), screens[screen])
        steps.append(Step(points=[[0.0, x, y], [0.1, x, y]], gap=gap, image=image))
    cv2.imwrite(str(folder / "end.jpg"), screens["home"])
    return Flow(name="商店来回", size=[2376, 1152], steps=steps, end_image="end.jpg", end_gap=3.0), folder

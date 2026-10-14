"""Screen checks used during replay.

An *anchor* is the small patch of screen under your finger, taken from the frame
just before you touched it. Replay waits until that patch is visible near the
same place before acting, so it follows the game's real pace instead of fixed
timers, and stops instead of tapping blindly when the screen is not what you saw.

Anchors are compared by their edges (gradient magnitude), not raw colours: game
buttons are often thin glyphs over backgrounds that change with the page behind
them. On the HONOR phone, the shop's back arrow scored 0.60 by colour against a
different shop tab (0.63 against the wrong screen); by edges it scored 0.74 vs 0.39.

All matching runs on frames scaled so the short side is WORK_SHORT pixels; this
keeps it fast and makes recordings tolerant to a changed display resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

WORK_SHORT = 576
ANCHOR_SIDE = 0.10  # anchor edge, as a fraction of the short side (~115 px on a 1152 px tall screen)
# How far an anchor may have moved, fraction of the short side (~115 px on the HONOR). Real moves seen:
# up to 33 px. 0.25 let a 9-minute auto-battle produce a 0.64 look-alike 330 px away.
SEARCH_RADIUS = 0.10
MIN_TEXTURE = 6.0  # mean edge strength below this: a flat or smoothly shaded patch (real buttons: 30-80)
SAME_SCREEN = 0.6  # fraction of grid cells that must correlate for "same screen"


def work_scale(size: tuple[int, int]) -> float:
    return WORK_SHORT / min(size)


def to_work(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = WORK_SHORT / min(h, w)
    return cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def edges(work: np.ndarray) -> np.ndarray:
    """Gradient magnitude: strong on outlines, icons and text, near zero on smooth shading."""
    grey = cv2.GaussianBlur(cv2.cvtColor(work, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.0)
    gx = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


@dataclass(frozen=True)
class Anchor:
    patch: np.ndarray  # edge magnitude, work scale
    origin: tuple[int, int]  # top-left in work coordinates of the recorded frame

    @property
    def texture(self) -> float:
        return float(self.patch.mean())


def make_anchor(frame: np.ndarray, point: tuple[float, float]) -> Anchor:
    """Patch centred on `point` (frame pixels), shifted inward near the edges."""
    work = edges(to_work(frame))
    scale = work_scale((frame.shape[1], frame.shape[0]))
    side = round(ANCHOR_SIDE * WORK_SHORT)
    h, w = work.shape[:2]
    x0 = int(min(max(round(point[0] * scale - side / 2), 0), w - side))
    y0 = int(min(max(round(point[1] * scale - side / 2), 0), h - side))
    return Anchor(work[y0 : y0 + side, x0 : x0 + side].copy(), (x0, y0))


@dataclass(frozen=True)
class Match:
    score: float
    shift: tuple[int, int]  # anchor displacement in work pixels

    def shift_in(self, size: tuple[int, int]) -> tuple[float, float]:
        """Displacement in pixels of a frame of `size`."""
        scale = work_scale(size)
        return self.shift[0] / scale, self.shift[1] / scale


def find_anchor(work: np.ndarray, anchor: Anchor) -> Match:
    """Best match of a work-scale frame within SEARCH_RADIUS of the recorded position.

    Among near-equal peaks (e.g. identical buttons in a list) the one closest to the
    recorded position wins.
    """
    work = edges(work)
    side = anchor.patch.shape[0]
    radius = round(SEARCH_RADIUS * WORK_SHORT)
    h, w = work.shape[:2]
    ox, oy = anchor.origin
    x0, y0 = max(ox - radius, 0), max(oy - radius, 0)
    x1, y1 = min(ox + side + radius, w), min(oy + side + radius, h)
    if x1 - x0 < side or y1 - y0 < side:
        return Match(0.0, (0, 0))
    scores = cv2.matchTemplate(work[y0:y1, x0:x1], anchor.patch, cv2.TM_CCOEFF_NORMED)
    scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)
    best = float(scores.max())
    ys, xs = np.nonzero(scores >= best - 0.02)
    dx, dy = xs + x0 - ox, ys + y0 - oy
    i = int(np.argmin(dx * dx + dy * dy))
    return Match(float(scores[ys[i], xs[i]]), (int(dx[i]), int(dy[i])))


def _grey_thumb(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    size = (256, 128) if w >= h else (128, 256)
    return cv2.cvtColor(cv2.resize(frame, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(
        np.float32
    )


def screen_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Fraction of a coarse grid whose cells correlate (>= 0.7) between two frames.

    Robust to animated characters in part of the screen; a different menu scores low.
    On real game screenshots: same screen 0.91-1.0, different screen ~0.2.
    """
    ta, tb = _grey_thumb(a), _grey_thumb(b)
    if ta.shape != tb.shape:
        return 0.0
    rows, cols = (4, 8) if ta.shape[1] >= ta.shape[0] else (8, 4)
    ch, cw = ta.shape[0] // rows, ta.shape[1] // cols
    good = 0
    for r in range(rows):
        for c in range(cols):
            pa = ta[r * ch : (r + 1) * ch, c * cw : (c + 1) * cw].ravel()
            pb = tb[r * ch : (r + 1) * ch, c * cw : (c + 1) * cw].ravel()
            sa, sb = pa.std(), pb.std()
            if sa < 2 or sb < 2:  # flat cells: compare brightness instead
                good += sa < 2 and sb < 2 and abs(pa.mean() - pb.mean()) < 12
                continue
            good += float(np.mean((pa - pa.mean()) * (pb - pb.mean())) / (sa * sb)) >= 0.7
    return good / (rows * cols)

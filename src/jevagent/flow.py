"""Recorded flows: what you did, stored as readable JSON next to the screenshots.

data/flows/<name>/
    flow.json         steps (gesture path + timing + replay settings)
    step-01.jpg ...   screen just before each gesture (source of its anchor)
    end.jpg           screen when you stopped recording
    getevent.log      raw touch events as received (for diagnosing a recording)
    report.html       visual review
    runs/<time>/      one folder per replay: run.json, last frame, report.html
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

FLOW_FILE = "flow.json"
LONG_PRESS = 0.45  # seconds; shorter holds are shown as taps
SETTLE_MAX = 1.5  # anchored steps start looking after min(recorded gap, this)
FIRST_STEP_TIMEOUT = 5.0  # you start replay on the start screen, so it should be there already
STEP_TIMEOUT = 10.0
MAX_TIMEOUT = 120.0
# Edge-match score an anchor needs (see vision.py). Real frames: same screen ~1.0, same button
# on a changed page 0.7-0.8, a different screen at most 0.46.
MATCH_THRESHOLD = 0.6
FLOW_VERSION = 2  # v2: anchors match edges; threshold None = MATCH_THRESHOLD


class FlowError(ValueError):
    pass


@dataclass
class Step:
    points: list[list[float]]  # [t, x, y]: seconds since touch-down, recorded-frame pixels
    gap: float  # idle seconds before this gesture while recording
    image: str  # frame just before the gesture
    label: str = ""
    check: bool = True  # wait for the anchor around the touch point before acting
    note: str = ""  # why the recorder turned the check off
    delay: float | None = None  # override: minimum wait before acting
    timeout: float | None = None  # override: how long to wait for the anchor
    threshold: float | None = None  # override: anchor match score needed

    @property
    def threshold_value(self) -> float:
        return MATCH_THRESHOLD if self.threshold is None else self.threshold

    @property
    def kind(self) -> str:
        x0, y0 = self.points[0][1:]
        if any(math.hypot(x - x0, y - y0) > 0 for _, x, y in self.points):
            return "swipe"
        return "long_press" if self.duration >= LONG_PRESS else "tap"

    @property
    def duration(self) -> float:
        return self.points[-1][0] - self.points[0][0]

    def describe(self) -> str:
        x, y = self.points[0][1:]
        if self.kind == "swipe":
            x1, y1 = self.points[-1][1:]
            return f"滑动 ({x:.0f},{y:.0f})→({x1:.0f},{y1:.0f}) {self.duration:.2f}s"
        if self.kind == "long_press":
            return f"长按 ({x:.0f},{y:.0f}) {self.duration:.2f}s"
        return f"点击 ({x:.0f},{y:.0f})"

    def delay_for(self, index: int) -> float:
        if self.delay is not None:
            return self.delay
        if index == 0:
            return 0.0
        return min(self.gap, SETTLE_MAX) if self.check else self.gap

    def timeout_for(self, index: int) -> float:
        if self.timeout is not None:
            return self.timeout
        if index == 0:
            return FIRST_STEP_TIMEOUT
        return min(max(STEP_TIMEOUT, 2 * self.gap), MAX_TIMEOUT)


@dataclass
class Flow:
    name: str
    size: list[int]  # [width, height] of the recorded frames
    steps: list[Step]
    end_image: str | None = None
    end_gap: float = 0.0  # seconds between the last gesture and stopping the recording
    end_check: bool = True  # require the final screen to match end.jpg
    device: dict = field(default_factory=dict)
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    revision: int = 1

    def end_timeout(self) -> float:
        return min(max(STEP_TIMEOUT, 2 * self.end_gap), 60.0)

    def to_json(self) -> dict:
        return {"version": FLOW_VERSION, **asdict(self)}

    @classmethod
    def from_json(cls, data: dict) -> Flow:
        version = data.get("version")
        if version not in (1, FLOW_VERSION):
            raise FlowError(f"不支持的 flow 版本: {version}")
        known = {f.name for f in fields(cls)}
        flow = cls(**{k: v for k, v in data.items() if k in known})
        flow.steps = [Step(**s) for s in data["steps"]]
        if version == 1:  # v1 compared colours and always stored its default 0.8
            for step in flow.steps:
                if step.threshold == 0.8:
                    step.threshold = None
        return flow


def validate_name(name: str) -> str:
    name = name.strip()
    if not name or name.startswith(".") or re.search(r'[/\\:*?"<>|\x00-\x1f]', name):
        raise FlowError(f'名称不能为空，不能以 . 开头或包含 / \\ : * ? " < > |：{name!r}')
    return name


def save(flow: Flow, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (FLOW_FILE + ".tmp")
    tmp.write_text(json.dumps(flow.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, folder / FLOW_FILE)


def load(folder: Path) -> Flow:
    path = folder / FLOW_FILE
    if not path.is_file():
        raise FlowError(f"没有这个流程: {folder.name}（{path} 不存在）")
    return Flow.from_json(json.loads(path.read_text(encoding="utf-8")))


_BOOL = {
    "on": True,
    "true": True,
    "yes": True,
    "1": True,
    "off": False,
    "false": False,
    "no": False,
    "0": False,
}
_STEP_FIELDS = {"label": str, "check": bool, "delay": float, "timeout": float, "threshold": float}


def _value(kind: type, text: str):
    if kind is bool:
        if text.lower() not in _BOOL:
            raise FlowError(f"需要 on/off: {text}")
        return _BOOL[text.lower()]
    if kind is float:
        if text.lower() in ("auto", "none", ""):
            return None
        try:
            number = float(text)
        except ValueError:
            raise FlowError(f"需要数字: {text}") from None
        if not 0 <= number <= MAX_TIMEOUT:
            raise FlowError(f"数值需在 0–{MAX_TIMEOUT:.0f} 之间: {text}")
        return number
    return text


def edit(flow: Flow, delete: list[int], assignments: list[str]) -> list[str]:
    """Apply `--set 3.check=off` style edits (1-based step numbers), then deletions.

    Returns human-readable change descriptions; raises FlowError without modifying
    the flow if any edit is invalid.
    """
    changes: list[tuple[Step | Flow, str, object]] = []
    log = []
    count = len(flow.steps)
    for item in assignments:
        target, sep, raw = item.partition("=")
        if not sep:
            raise FlowError(f"格式应为 步骤.字段=值 或 end_check=on/off: {item}")
        if target == "end_check":
            changes.append((flow, "end_check", _value(bool, raw)))
            log.append(f"end_check = {raw}")
            continue
        number, dot, name = target.partition(".")
        if not dot or not number.isdigit() or name not in _STEP_FIELDS:
            raise FlowError(f"未知字段 {target}；可用: 步骤号.{{{','.join(_STEP_FIELDS)}}}, end_check")
        index = int(number) - 1
        if not 0 <= index < count:
            raise FlowError(f"没有第 {number} 步（共 {count} 步）")
        value = _value(_STEP_FIELDS[name], raw)
        if name == "threshold" and value is not None and not 0.3 <= value <= 0.99:
            raise FlowError("threshold 需在 0.3–0.99 之间（auto 恢复默认）")
        changes.append((flow.steps[index], name, value))
        log.append(f"第 {number} 步 {name} = {raw}")
    for number in delete:
        if not 1 <= number <= count:
            raise FlowError(f"没有第 {number} 步（共 {count} 步）")
    if len(set(delete)) == count:
        raise FlowError("不能删除全部步骤；不需要这个流程时直接删除它的目录")
    for target, name, value in changes:
        setattr(target, name, value)
    for number in sorted(set(delete), reverse=True):
        log.append(f"删除第 {number} 步: {flow.steps[number - 1].describe()}")
        del flow.steps[number - 1]
    if log:
        flow.revision += 1
    return log

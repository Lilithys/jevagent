"""Run recorded flows back to back as one round of a game routine, for several rounds.

Example (the club-challenge loop): A-战斗, then B-普通宝箱 again and again while a full chest
is waiting, then C-滴答宝箱; repeat. Every flow checks its own start screen, so a problem stops
the routine inside the flow where it happened instead of carrying on with the next one.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from jevagent import flow as flows
from jevagent.errors import DeviceError, Interrupted
from jevagent.player import Player, RunResult, new_run_dir
from jevagent.report import write_flow_report, write_run_report

MAX_REPEAT = 8  # a repeated flow runs at most this many times per round (6 chest slots + margin)
READY_WAIT = 5.0  # how long a repeated flow waits for its start screen before it counts as done


@dataclass
class Segment:
    round: int
    flow: str  # folder name, as given on the command line
    result: RunResult
    run_dir: Path


def run_routine(
    device,
    folders: list[Path],
    repeat: set[str],
    rounds: int,
    *,
    until_empty: set[str] = frozenset(),
    stop: threading.Event | None = None,
    log: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] | None = None,
) -> tuple[str, str, list[Segment]]:
    """Returns (status, reason, segments); status is success | failed | stopped | error.

    rounds=0 means no limit. A repeated flow named in `until_empty` that finds nothing to do in a
    round ends the whole routine (e.g. the day's chests are used up).
    """
    stop = stop or threading.Event()
    loaded = [(folder, flows.load(folder)) for folder in folders]
    segments: list[Segment] = []
    try:
        for number in itertools.count(1) if rounds == 0 else range(1, rounds + 1):
            log(f"\n======== 第 {number}{f'/{rounds}' if rounds else ''} 轮 ========")
            for folder, flow in loaded:
                repeated = folder.name in repeat
                for attempt in range(MAX_REPEAT if repeated else 1):
                    player = Player(device, flow, folder, log=log, clock=clock, sleep=sleep, stop=stop)
                    if repeated and not player.ready(READY_WAIT):
                        if attempt == 0 and folder.name in until_empty:
                            log(f"「{flow.name}」这一轮没有可做的了，循环结束")
                            return "success", f"第 {number} 轮「{flow.name}」没有可做的了，循环结束", segments
                        log(f"「{flow.name}」没有可做的了（共做了 {attempt} 次），继续下一段")
                        break
                    log(f"—— {flow.name}" + (f"（第 {attempt + 1} 次）" if repeated else "") + " ——")
                    run_dir = new_run_dir(folder)
                    result = player.run(run_dir)
                    write_run_report(flow, folder, run_dir, asdict(result))
                    segments.append(Segment(number, folder.name, result, run_dir))
                    if result.status != "success":
                        return result.status, f"第 {number} 轮「{flow.name}」：{result.reason}", segments
                else:
                    if repeated:
                        log(f"「{flow.name}」已做满 {MAX_REPEAT} 次，继续下一段")
        return "success", f"{rounds} 轮全部完成", segments  # (unreachable when rounds == 0)
    except (Interrupted, KeyboardInterrupt):
        return "stopped", "手动停止", segments
    except DeviceError as exc:
        return "error", str(exc), segments
    finally:
        for folder, flow in loaded:
            write_flow_report(flow, folder)

"""jevagent command line.

jevagent devices                 list phones visible to adb
jevagent check                   read-only: screen size, capture speed, touchscreen
jevagent record NAME             record a flow while you play on the phone
jevagent play NAME [--times N]   replay it
jevagent list                    flows and their replay results
jevagent show NAME               print the steps and open the visual report
jevagent edit NAME ...           delete steps / change replay settings
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

from jevagent import flow as flows
from jevagent.errors import DeviceError
from jevagent.flow import FlowError

DATA = Path(os.environ.get("JEVAGENT_DATA") or Path(__file__).resolve().parents[2] / "data")


def flows_dir() -> Path:
    return DATA / "flows"


def flow_dir(name: str) -> Path:
    return flows_dir() / flows.validate_name(name)


def connect(args: argparse.Namespace):
    from jevagent.device import AndroidDevice

    print("连接手机…（首次截图要在手机上启动截图服务，约 5–10 秒）", flush=True)
    device = AndroidDevice(serial=args.serial, adb_path=args.adb)
    try:
        device.frame()
    except BaseException:
        device.close()
        raise
    width, height = device.size
    print(
        f"设备 {device.serial} ({device.info.model})  画面 {width}×{height}  "
        f"首帧 {device.last_frame_seconds:.1f}s（含启动截图服务）",
        flush=True,
    )
    return device


def open_file(path: Path) -> None:
    if sys.platform == "darwin" and shutil.which("open"):
        subprocess.run(["open", str(path)], check=False)


def print_steps(flow: flows.Flow) -> None:
    for i, step in enumerate(flow.steps):
        if step.check:
            check = f"检查画面≥{step.threshold_value:.2f}"
            if step.look:
                check += f"（看 ({step.look[0]:.0f},{step.look[1]:.0f}) 处）"
            if step.until_next:
                check += f"，没反应再点（最多 {flows.RETRY_TAPS} 次）"
            if step.optional:
                check += "，可选：没出现就跳过"
            if step.react:
                check += "，应对：出现就做（可多次）"
        elif step.react:
            check = "应对：长时间没有可识别画面时轻点一下（最多 3 次）"
        elif step.until_next:
            check = f"点空白处，点到下一画面出现（最多 {flows.RETRY_TAPS} 次）"
        else:
            check = f"不检查画面（{step.note or '手动关闭'}）"
        timeout = f" 最多等 {step.timeout_for(i):.0f}s" if step.check else ""
        label = f"「{step.label}」" if step.label else ""
        print(
            f"  {i + 1:>2}. {label}{step.describe():<34} 间隔 {step.gap:>5.1f}s  "
            f"先等 {step.delay_for(i):.1f}s{timeout}  {check}"
        )
    where = f"看 ({flow.end_look[0]:.0f},{flow.end_look[1]:.0f}) 处" if flow.end_look else "整屏"
    end = f"要求一致（{where}，最多等 {flow.end_timeout():.0f}s）" if flow.end_check else "不检查"
    print(f"  结束画面：{end}")


def cmd_devices(args: argparse.Namespace) -> int:
    from jevagent.device import list_devices, resolve_adb

    adb = resolve_adb(args.adb)
    devices = list_devices(adb)
    print(f"adb: {adb}")
    for d in devices:
        print(f"  {d.serial}  {d.state}  {d.model}")
    if not devices:
        print("  （没有设备：连接数据线，打开开发者选项里的 USB 调试，并在手机上允许这台电脑）")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from jevagent.recorder import save_jpeg

    device = connect(args)
    try:
        natural, orientation = device.display()
        screen = device.touchscreen()
        timings = []
        for _ in range(5):
            frame = device.frame()
            timings.append(device.last_frame_seconds)
        DATA.mkdir(parents=True, exist_ok=True)
        save_jpeg(DATA / "check.jpg", frame)
    finally:
        device.close()
    width, height = device.size
    print(
        f"屏幕方向 {orientation}（{'横屏' if width > height else '竖屏'}），自然尺寸 {natural[0]}×{natural[1]}"
    )
    print(
        f'触摸屏 {screen.path} "{screen.name}"  X {screen.x_range}  Y {screen.y_range}  '
        f"多点触控协议 {screen.protocol}"
    )
    print(f"截图 {sum(timings) / len(timings):.2f}s/帧（5 帧平均）；当前画面已保存: {DATA / 'check.jpg'}")
    print("只读检查，没有发送任何触摸。")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    from jevagent.recorder import RAW_LOG, Recorder
    from jevagent.report import write_flow_report

    target = flow_dir(args.name)
    base = None
    if args.start is not None:  # re-record only the tail of an existing flow
        if args.force:
            print("--from 和 --force 不能同时使用。")
            return 2
        base = flows.load(target)
        if not 1 <= args.start <= len(base.steps) + 1:
            print(f"--from 需在 1–{len(base.steps) + 1} 之间（「{base.name}」共 {len(base.steps)} 步）。")
            return 2
    elif target.exists() and not args.force:
        print(f"流程「{args.name}」已存在。换个名字，或加 --force 删除旧流程（含回放记录）后重录，")
        print("或用 --from N 只重录第 N 步及之后。")
        return 2
    tmp = flows_dir() / f".recording-{target.name}"
    shutil.rmtree(tmp, ignore_errors=True)
    tag = f"-v{base.revision + 1}" if base else ""
    device = connect(args)
    recorder = Recorder(device, tmp, first_index=args.start or 1, tag=tag)
    try:
        recorder.start()
        if base and args.start > 1:
            print(
                f"\n只重录第 {args.start} 步及之后：保留第 1–{args.start - 1} 步，"
                f"原第 {args.start}–{len(base.steps)} 步和结束画面会被替换。"
                f"\n请让手机停在第 {args.start - 1} 步刚做完时的画面。"
            )
        print("\n开始录制。在手机上像平时一样操作（点击、长按、滑动）。")
        print("最后一步做完、画面停稳后，回到这里按 Enter 结束；Ctrl+C 放弃。\n", flush=True)
        input()
        flow = recorder.finish(target.name)
    except KeyboardInterrupt:
        recorder.stop()
        shutil.rmtree(tmp, ignore_errors=True)
        print("\n已放弃，没有保存。")
        return 130
    except BaseException:
        recorder.stop()
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        device.close()
    if not flow.steps:
        raw = tmp / RAW_LOG
        if raw.is_file():  # keep the raw touch stream so a failed recording can be diagnosed
            shutil.copyfile(raw, DATA / f"last-{RAW_LOG}")
        shutil.rmtree(tmp, ignore_errors=True)
        print("没有录到手势，未保存。确认是在手机屏幕上操作的。")
        print(f"手机原始触摸记录已保留：{DATA / f'last-{RAW_LOG}'}")
        return 1
    if base:
        recorded = len(flow.steps)
        try:
            flow = flows.splice(base, flow, args.start)
        except FlowError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        for item in tmp.iterdir():  # new files carry the tag, so the kept steps' images stay intact
            os.replace(item, target / (f"getevent{tag}.log" if item.name == RAW_LOG else item.name))
        shutil.rmtree(tmp, ignore_errors=True)
        flows.save(flow, target)
        print(
            f"\n已更新「{flow.name}」：保留前 {args.start - 1} 步，新录 {recorded} 步，共 {len(flow.steps)} 步。"
        )
    else:
        flows.save(flow, tmp)
        if target.exists():
            shutil.rmtree(target)
        tmp.rename(target)
    report = write_flow_report(flow, target)
    unchecked = [str(i + 1) for i, s in enumerate(flow.steps) if not s.check and not s.until_next]
    blank = [str(i + 1) for i, s in enumerate(flow.steps) if s.until_next]
    if not base:
        print(f"\n已保存「{flow.name}」：{len(flow.steps)} 步 → {target}")
    if recorder.error:
        print(f"注意：录制中出过错（{recorder.error}），请检查步骤是否完整。")
    if blank:
        print(f"第 {', '.join(blank)} 步点在空白处：回放时点到下一画面出现为止。")
    if unchecked:
        print(f"第 {', '.join(unchecked)} 步回放时按录制节奏点击，不检查画面（见报告里的原因）。")
    print(f"先打开报告核对红圈是否点在你按的位置：{report}")
    open_file(report)
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    from jevagent.player import STATUS, Player, new_run_dir
    from jevagent.report import write_flow_report, write_run_report

    folder = flow_dir(args.name)
    flow = flows.load(folder)
    if not 1 <= args.start <= len(flow.steps):
        print(f"--from 需在 1–{len(flow.steps)} 之间。")
        return 2
    device = connect(args)
    stop = threading.Event()
    results = []
    try:
        print(f"触摸服务已就绪（{device.prepare_input()}）", flush=True)
        if sys.stdin.isatty():
            # Enter stops cleanly: the current gesture is released before stopping. Ctrl+C also
            # kills Airtest's helper adb processes, so a finger held at that moment may stay down.
            threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
        print(
            f"\n回放「{flow.name}」（{len(flow.steps)} 步，第 {flow.revision} 版）。"
            "请确认手机停在录制时的起始画面；按 Enter 停止。\n",
            flush=True,
        )
        for k in range(args.times):
            if args.times > 1:
                print(f"—— 第 {k + 1}/{args.times} 次 ——", flush=True)
            run_dir = new_run_dir(folder)
            first = args.start if k == 0 else 1  # --from applies to the first run only
            if first > 1:
                print(f"从第 {first} 步开始（前 {first - 1} 步已手动完成）", flush=True)
            result = Player(
                device, flow, folder, stop=stop, log=lambda s: print(s, flush=True), start=first
            ).run(run_dir)
            report = write_run_report(flow, folder, run_dir, asdict(result))
            results.append(result)
            print(f"\n结果：{STATUS[result.status]}。{result.reason}\n报告：{report}\n", flush=True)
            if result.status != "success":
                break
            time.sleep(0.5)
    finally:
        device.close()
        write_flow_report(flow, folder)
    ok = sum(r.status == "success" for r in results)
    if args.times > 1:
        print(f"共 {len(results)} 次，成功 {ok} 次。")
    if results and results[-1].status == "stopped":
        return 130
    return 0 if ok == args.times else 1


def cmd_loop(args: argparse.Namespace) -> int:
    from jevagent.player import STATUS
    from jevagent.routine import run_routine

    folders = [flow_dir(name) for name in args.names]
    for folder in folders:
        flows.load(folder)  # fail early on a missing flow, before connecting
    unknown = set(args.repeat or []) - {folder.name for folder in folders}
    if unknown:
        print(f"--repeat 的流程不在循环里: {', '.join(sorted(unknown))}")
        return 2
    if set(args.until_empty or []) - set(args.repeat or []):
        print("--until-empty 的流程也要用 --repeat 标记（重复做到没有为止的那一段）")
        return 2
    if args.times == 0 and not args.until_empty:
        print("提示：--times 0 且没有 --until-empty，会一直循环到失败或按 Enter。")
    device = connect(args)
    stop = threading.Event()
    started = time.monotonic()
    try:
        print(f"触摸服务已就绪（{device.prepare_input()}）", flush=True)
        if sys.stdin.isatty():
            threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
        order = " → ".join(f"{n}（重复到没有为止）" if n in (args.repeat or []) else n for n in args.names)
        rounds = f"{args.times} 轮" if args.times else "不限轮数"
        ending = f"；「{'、'.join(args.until_empty)}」一轮里没有可做的就结束" if args.until_empty else ""
        print(
            f"\n循环（{rounds}{ending}）：{order}。请停在「{args.names[0]}」的起始画面；按 Enter 停止。",
            flush=True,
        )
        status, reason, segments = run_routine(
            device,
            folders,
            set(args.repeat or []),
            args.times,
            until_empty=set(args.until_empty or []),
            stop=stop,
            log=lambda s: print(s, flush=True),
        )
    finally:
        device.close()
    print(f"\n结果：{STATUS[status]}。{reason}（用时 {(time.monotonic() - started) / 60:.1f} 分钟）")
    for number in sorted({seg.round for seg in segments}):
        parts = []
        for name in args.names:
            runs = [seg for seg in segments if seg.round == number and seg.flow == name]
            ok = sum(seg.result.status == "success" for seg in runs)
            mark = "✓" if runs and ok == len(runs) else ("✗" if runs else "—")
            parts.append(f"{name}{f' ×{len(runs)}' if len(runs) > 1 else ''} {mark}")
        print(f"  第 {number} 轮：" + " · ".join(parts))
    shots = [seg.run_dir / name for seg in segments for name in seg.result.shots]
    if shots:
        print(f"\n应对时的截图（如金卡）共 {len(shots)} 张：")
        for path in shots:
            print(f"  {path}")
    if status == "stopped":
        return 130
    return 0 if status == "success" else 1


def cmd_list(args: argparse.Namespace) -> int:
    from jevagent.player import STATUS, load_runs

    found = False
    for folder in sorted(flows_dir().glob("*/flow.json")):
        folder = folder.parent
        if folder.name.startswith("."):
            continue
        try:
            flow = flows.load(folder)
        except (FlowError, ValueError, TypeError, KeyError) as exc:
            print(f"  {folder.name}: 无法读取 ({exc})")
            continue
        found = True
        runs = load_runs(folder)
        ok = sum(run.get("status") == "success" for _, run in runs)
        last = f"  最近一次 {runs[-1][0].name} {STATUS.get(runs[-1][1].get('status'), '?')}" if runs else ""
        print(f"  {flow.name}  {len(flow.steps)} 步  回放 {len(runs)} 次，成功 {ok} 次{last}")
    if not found:
        print("还没有流程。用 jevagent record 名称 录一个。")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    from jevagent.report import write_flow_report

    folder = flow_dir(args.name)
    flow = flows.load(folder)
    print(f"{flow.name}：{len(flow.steps)} 步，{flow.size[0]}×{flow.size[1]}，第 {flow.revision} 版")
    print_steps(flow)
    report = write_flow_report(flow, folder)
    print(f"报告：{report}")
    if not args.no_open:
        open_file(report)
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    from jevagent.report import write_flow_report

    folder = flow_dir(args.name)
    flow = flows.load(folder)
    changes = flows.edit(flow, args.delete or [], args.set or [])
    if not changes:
        print_steps(flow)
        print("\n例：jevagent edit 名称 --delete 3 --set 2.check=off --set 4.timeout=30 --set 5.label=领取")
        return 0
    flows.save(flow, folder)
    write_flow_report(flow, folder)
    for line in changes:
        print(f"  {line}")
    print(f"已保存为第 {flow.revision} 版。")
    print_steps(flow)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jevagent", description="录制并回放手机游戏里的固定操作流程（M0）")
    sub = parser.add_subparsers(dest="command", required=True)

    def device_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--serial", help="adb 设备序列号（多台设备时必填）")
        p.add_argument("--adb", help="adb 路径（默认 PATH 中的 adb）")

    device_args(sub.add_parser("devices", help="列出 adb 能看到的设备"))
    device_args(sub.add_parser("check", help="只读检查：画面尺寸、截图速度、触摸屏"))
    p = sub.add_parser("record", help="在手机上操作，录成流程")
    p.add_argument("name")
    p.add_argument("--force", action="store_true", help="覆盖同名流程（旧回放记录一并删除）")
    p.add_argument("--from", dest="start", type=int, metavar="N", help="只重录第 N 步及之后，保留前面的步骤")
    device_args(p)
    p = sub.add_parser("play", help="回放流程")
    p.add_argument("name")
    p.add_argument("--times", type=int, default=1, help="连续回放次数（流程须结束在起始画面），失败即停")
    p.add_argument(
        "--from", dest="start", type=int, default=1, metavar="N", help="从第 N 步开始（前面的已手动做完）"
    )
    device_args(p)
    p = sub.add_parser("loop", help="把几个流程连起来按顺序回放，循环多轮")
    p.add_argument("names", nargs="+", metavar="流程", help="按顺序回放的流程")
    p.add_argument(
        "--repeat", action="append", metavar="流程", help="这个流程重复做到起始画面不再出现为止（如开宝箱）"
    )
    p.add_argument("--times", type=int, default=1, help="循环轮数；0 = 不限，直到 --until-empty 的条件或失败")
    p.add_argument(
        "--until-empty",
        action="append",
        metavar="流程",
        help="这个重复流程在一轮里一次都做不了时结束整个循环（如宝箱用完）",
    )
    device_args(p)
    sub.add_parser("list", help="列出流程和回放结果")
    p = sub.add_parser("show", help="打印步骤并打开报告")
    p.add_argument("name")
    p.add_argument("--no-open", action="store_true")
    p = sub.add_parser("edit", help="删除步骤或修改回放设置；不带参数时列出步骤")
    p.add_argument("name")
    p.add_argument("--delete", type=int, nargs="+", metavar="N", help="删除第 N 步（可多个）")
    p.add_argument(
        "--set",
        action="append",
        metavar="N.字段=值",
        help="字段: label, check(on/off), until_next(on/off), optional(on/off), react(on/off), delay, timeout(秒), threshold(默认 0.6), look(x,y：检查这里而不是触点)，填 auto 恢复默认；或 end_check=on/off",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "times", 1) < (0 if args.command == "loop" else 1):
        print("--times 至少为 1（loop 可用 0 表示不限轮数）")
        return 2
    handler = {
        "loop": cmd_loop,
        "devices": cmd_devices,
        "check": cmd_check,
        "record": cmd_record,
        "play": cmd_play,
        "list": cmd_list,
        "show": cmd_show,
        "edit": cmd_edit,
    }[args.command]
    try:
        return handler(args)
    except (FlowError, DeviceError) as exc:
        print(f"错误：{exc}")
        return 1
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130

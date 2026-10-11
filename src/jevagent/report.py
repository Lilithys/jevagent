"""Static HTML pages for reviewing a recorded flow and its replays (open in any browser)."""

from __future__ import annotations

import html
import os
from pathlib import Path

from jevagent.flow import Flow, Step
from jevagent.player import STATUS, load_runs
from jevagent.vision import ANCHOR_SIDE

CSS = """
:root { --bg:#f6f6f4; --card:#fff; --text:#1d1d1b; --muted:#6b6b66; --line:#e2e1dc;
        --ok:#1f7a4d; --bad:#b3261e; --warn:#8a5a00; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161615; --card:#21211f; --text:#ececea; --muted:#a3a29c; --line:#34332f;
          --ok:#5cc28b; --bad:#ff7b72; --warn:#e3b341; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.5 -apple-system, "PingFang SC", "Helvetica Neue", sans-serif; }
main { max-width:1180px; margin:0 auto; padding:24px 16px 48px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 10px; }
.meta { color:var(--muted); margin:0 0 16px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 480px), 1fr)); gap:14px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
.card .shot { position:relative; line-height:0; }
.card img { width:100%; height:auto; display:block; }
.card svg { position:absolute; inset:0; width:100%; height:100%; }
.card .body { padding:10px 12px 12px; }
.card .title { font-weight:600; }
.small { color:var(--muted); font-size:13px; }
.tag { display:inline-block; font-size:12px; padding:1px 7px; border-radius:99px; border:1px solid var(--line); }
.ok { color:var(--ok); } .bad { color:var(--bad); } .warn { color:var(--warn); }
table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line);
        border-radius:10px; overflow:hidden; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); font-size:14px; vertical-align:top; }
th { color:var(--muted); font-weight:500; }
code { font-family: ui-monospace, Menlo, monospace; font-size:13px; }
"""


def _page(title: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>"
    )


def _overlay(step: Step, size: list[int]) -> str:
    """SVG drawn in recorded-frame pixel coordinates: anchor box (blue) and gesture (red)."""
    w, h = size
    pts = [(x, y) for _, x, y in step.points]
    r = max(min(w, h) * 0.03, 6)
    parts = []
    if step.check:
        side = ANCHOR_SIDE * min(w, h)
        x0 = min(max(pts[0][0] - side / 2, 0), w - side)
        y0 = min(max(pts[0][1] - side / 2, 0), h - side)
        parts.append(
            f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{side:.0f}" height="{side:.0f}" fill="none" '
            f'stroke="#0a84ff" stroke-width="{r / 3:.1f}" stroke-dasharray="{r:.0f} {r / 2:.0f}"/>'
        )
    if step.kind == "swipe":
        path = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        parts.append(
            f'<polyline points="{path}" fill="none" stroke="#ff3b30" stroke-width="{r / 2.5:.1f}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        parts.append(f'<circle cx="{pts[-1][0]:.0f}" cy="{pts[-1][1]:.0f}" r="{r / 2:.0f}" fill="#ff3b30"/>')
    parts.append(
        f'<circle cx="{pts[0][0]:.0f}" cy="{pts[0][1]:.0f}" r="{r:.0f}" fill="none" '
        f'stroke="#ff3b30" stroke-width="{r / 3:.1f}"/>'
    )
    return f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">{"".join(parts)}</svg>'


def _settings(step: Step, index: int) -> str:
    check = (
        f'<span class="tag ok">检查画面 ≥{step.threshold_value:.2f}</span>'
        if step.check
        else f'<span class="tag warn">不检查画面</span> <span class="small">{html.escape(step.note)}</span>'
    )
    wait = f"先等 {step.delay_for(index):.1f}s"
    if step.check:
        wait += f"，最多等画面 {step.timeout_for(index):.0f}s"
    return f'{check}<div class="small">录制时间隔 {step.gap:.1f}s · 回放{wait}</div>'


def write_flow_report(flow: Flow, folder: Path) -> Path:
    cards = []
    for i, step in enumerate(flow.steps):
        label = html.escape(f"{step.label} · {step.describe()}" if step.label else step.describe())
        cards.append(
            f'<div class="card"><div class="shot"><img src="{html.escape(step.image)}" loading="lazy" alt="">'
            f'{_overlay(step, flow.size)}</div><div class="body"><div class="title">{i + 1}. {label}</div>'
            f"{_settings(step, i)}</div></div>"
        )
    if flow.end_image:
        end_note = (
            f"回放结束后最多等 {flow.end_timeout():.0f}s，要求画面与此一致"
            if flow.end_check
            else "不检查结束画面"
        )
        cards.append(
            f'<div class="card"><div class="shot"><img src="{flow.end_image}" loading="lazy" alt=""></div>'
            f'<div class="body"><div class="title">结束画面</div><div class="small">{end_note}</div></div></div>'
        )
    rows = []
    for run_dir, run in reversed(load_runs(folder)[-30:]):
        status = run.get("status", "running")
        css = "ok" if status == "success" else "bad"
        link = os.path.relpath(run_dir / "report.html", folder)
        rows.append(
            f'<tr><td><a href="{html.escape(link)}">{html.escape(run_dir.name)}</a></td>'
            f'<td class="{css}">{STATUS.get(status, status)}</td>'
            f"<td>{len([s for s in run.get('steps', []) if s.get('status') == 'done'])}/{len(flow.steps)}</td>"
            f"<td>{html.escape(run.get('reason', ''))}</td></tr>"
        )
    runs = (
        f"<h2>回放记录</h2><table><tr><th>时间</th><th>结果</th><th>完成步数</th><th>说明</th></tr>{''.join(rows)}</table>"
        if rows
        else ""
    )
    device = flow.device.get("model") or flow.device.get("serial")
    meta = [
        f"{len(flow.steps)} 步",
        f"{flow.size[0]}×{flow.size[1]}",
        *([device] if device else []),
        f"录制于 {flow.created.replace('T', ' ')}",
        f"第 {flow.revision} 版",
    ]
    body = (
        f'<h1>{html.escape(flow.name)}</h1><p class="meta">{html.escape(" · ".join(meta))}'
        f"<br>红圈/红线是你的手势，蓝框是回放时要先在屏幕上找到的画面（锚点）。</p>"
        f'<div class="grid">{"".join(cards)}</div>{runs}'
    )
    path = folder / "report.html"
    path.write_text(_page(flow.name, body), encoding="utf-8")
    return path


def _image_card(src: str, overlay: str, caption: str) -> str:
    return (
        f'<div class="card"><div class="shot"><img src="{html.escape(src)}" alt="">{overlay}</div>'
        f'<div class="body small">{html.escape(caption)}</div></div>'
    )


def write_run_report(flow: Flow, folder: Path, run_dir: Path, run: dict) -> Path:
    status = run.get("status", "running")
    css = "ok" if status == "success" else "bad"
    rows = []
    for item in run.get("steps", []):
        n = item["step"]
        step = flow.steps[n - 1] if n <= len(flow.steps) else None
        name = html.escape(step.label or step.describe()) if step else "?"
        score = "" if item.get("score") is None else f"{item['score']:.2f}"
        mark = "✓" if item["status"] == "done" else "✗"
        rows.append(
            f'<tr><td>{n}</td><td>{name}</td><td class="{"ok" if mark == "✓" else "bad"}">{mark}</td>'
            f"<td>{score}</td><td>{item.get('waited', 0):.1f}s</td>"
            f"<td>{html.escape(item.get('error', ''))}</td></tr>"
        )
    shot = ""
    if run.get("image"):
        failed = next((s["step"] for s in run.get("steps", []) if s["status"] == "failed"), None)
        step = flow.steps[failed - 1] if failed and failed <= len(flow.steps) else None
        overlay = _overlay(step, flow.size) if step else ""
        cards = [_image_card(run["image"], overlay, "回放时的画面" if step else "回放结束时的画面")]
        if step:
            cards.append(
                _image_card(os.path.relpath(folder / step.image, run_dir), overlay, "录制时这一步之前的画面")
            )
        title = f"第 {failed} 步失败时（蓝框/红圈是录制时的位置）" if step else "最后的画面"
        shot = f'<h2>{title}</h2><div class="grid">{"".join(cards)}</div>'
    end = "" if run.get("end_score") is None else f" · 结束画面相似度 {run['end_score']:.2f}"
    started = run.get("started", "").replace("T", " ")
    body = (
        f'<h1>{html.escape(flow.name)} · <span class="{css}">{STATUS.get(status, status)}</span></h1>'
        f'<p class="meta">{html.escape(started)} · 用时 {run.get("seconds", 0):.0f}s · '
        f"流程第 {run.get('revision', '?')} 版{end}<br>{html.escape(run.get('reason', ''))}</p>"
        f"<table><tr><th>#</th><th>步骤</th><th>结果</th><th>画面匹配</th><th>等待</th><th>说明</th></tr>"
        f"{''.join(rows)}</table>{shot}"
        f'<p class="small"><a href="{html.escape(os.path.relpath(folder / "report.html", run_dir))}">返回流程</a></p>'
    )
    path = run_dir / "report.html"
    path.write_text(_page(f"{flow.name} 回放", body), encoding="utf-8")
    return path

"""A cost and quality dashboard: one self-contained HTML page built from your local store.

``crossvet chat dashboard --out dashboard.html`` writes it. Every number is counted in code from
saved answers and ratings over the chosen days (nothing is typed in, and nothing leaves the
machine). Headline numbers sit in tiles; each chart is one series in one hue, with a hover
tooltip on every bar, its value at the bar's end, and a table view under it. It follows the
reader's light or dark setting.
"""

from __future__ import annotations

import html
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crossvet.chat.hub import Hub


def data(hub: Hub, days: float = 30, now: float | None = None) -> dict[str, Any]:
    """Return the dashboard's numbers for the last ``days``."""
    now = now or time.time()
    since = now - days * 86400
    answers = hub.memory.answers(since=since)
    feedback: dict[int, float] = {}
    for rating in hub.memory.ratings(since=since):
        if rating.name == "user-feedback":
            feedback[rating.turn_id] = rating.value
    per_day: dict[str, float] = defaultdict(float)
    per_model: dict[str, int] = defaultdict(int)
    per_slot: dict[str, int] = defaultdict(int)
    kind_rated: dict[str, list[float]] = defaultdict(list)
    for a in answers:
        per_day[time.strftime("%Y-%m-%d", time.localtime(a.ts))] += a.cost or 0.0
        per_model[a.model or "-"] += 1
        per_slot[str(a.meta.get("slot") or "-")] += 1
        if a.id in feedback:
            kind_rated[str(a.meta.get("kind") or "-")].append(feedback[a.id])
    priced = [a.cost for a in answers if a.cost is not None]
    rated = list(feedback.values())
    escalated = sum(len(a.meta.get("attempts") or []) > 1 for a in answers)
    inputs = sum(int((a.meta.get("usage") or {}).get("input", 0) or 0) for a in answers)
    cached = sum(int((a.meta.get("usage") or {}).get("cached", 0) or 0) for a in answers)
    return {
        "days": days, "from": time.strftime("%b %d, %Y", time.localtime(since)), "to": time.strftime("%b %d, %Y", time.localtime(now)),
        "answers": len(answers), "spend": sum(priced) if priced else None, "priced": len(priced),
        "rated": len(rated), "good_rate": sum(v >= 0.5 for v in rated) / len(rated) if rated else None,
        "escalation_rate": escalated / len(answers) if answers else None,
        "cached_share": cached / inputs if inputs else None,
        "private": sum(bool(a.meta.get("private")) for a in answers),
        "spend_per_day": dict(sorted(per_day.items())),
        "answers_per_model": dict(sorted(per_model.items(), key=lambda kv: -kv[1])),
        "answers_per_slot": dict(sorted(per_slot.items(), key=lambda kv: -kv[1])),
        "good_rate_per_kind": {k: sum(v >= 0.5 for v in vals) / len(vals) for k, vals in sorted(kind_rated.items())},
        "rated_per_kind": {k: len(v) for k, v in kind_rated.items()},
    }


CSS = """
:root { --surface:#ffffff; --plane:#f9f9f9; --ink:#191919; --ink2:#666666; --grid:#e7e7e7; --axis:#c2c2c2;
        --mark:#257de0; --ring:rgba(11,11,11,0.10); }
@media (prefers-color-scheme: dark) {
  :root { --surface:#191919; --plane:#0b0b0b; --ink:#efefef; --ink2:#9c9c9c; --grid:#303030; --axis:#474747;
          --mark:#338ced; --ring:rgba(255,255,255,0.10); } }
* { box-sizing: border-box; }
body { margin:0; padding:24px; background:var(--plane); color:var(--ink);
       font:14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
h1 { font-size:20px; margin:0 0 4px; } .sub { color:var(--ink2); margin:0 0 20px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px; margin-bottom:20px; }
.tile, .card { background:var(--surface); border:1px solid var(--ring); border-radius:10px; padding:14px 16px; }
.tile .label { color:var(--ink2); font-size:12px; } .tile .value { font-size:24px; font-weight:600; margin-top:2px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(380px, 1fr)); gap:12px; }
.card h2 { font-size:14px; margin:0 0 10px; }
svg text { fill:var(--ink2); font-size:12px; } svg .value { fill:var(--ink); }
.bar { fill:var(--mark); } .bar:hover { opacity:.8; } .gridline { stroke:var(--grid); } .axis { stroke:var(--axis); }
details { margin-top:8px; color:var(--ink2); } table { border-collapse:collapse; margin-top:6px; width:100%; }
td, th { text-align:left; padding:3px 6px; border-bottom:1px solid var(--grid); color:var(--ink); font-weight:normal; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.empty { color:var(--ink2); }
"""


def _bars(values: dict[str, float], fmt: Any, scale_max: float | None = None) -> str:
    """Horizontal bars, one hue, rounded at the data end only, value at the end, a tooltip on each bar."""
    if not values:
        return '<p class="empty">No data yet.</p>'
    label_w, chart_w, row, gap = 170, 220, 22, 6
    top = scale_max if scale_max is not None else max(values.values()) or 1.0
    height = len(values) * (row + gap)
    parts = [f'<svg role="img" width="100%" viewBox="0 0 {label_w + chart_w + 70} {height + 4}">',
             f'<line class="axis" x1="{label_w}" x2="{label_w}" y1="0" y2="{height}" />']
    for i, (name, value) in enumerate(values.items()):
        y = i * (row + gap)
        w = max(chart_w * (value / top), 0)
        r = min(4.0, w)
        path = (f"M{label_w},{y} h{w - r:.1f} q{r},0 {r},{r} v{row - 2 * r} q0,{r} {-r},{r} h{-(w - r):.1f} z" if w > 0
                else "")
        short = name if len(name) <= 24 else name[:23] + "…"
        parts.append(f'<text x="{label_w - 8}" y="{y + row / 2 + 4}" text-anchor="end">{html.escape(short)}</text>')
        if path:
            parts.append(f'<path class="bar" d="{path}"><title>{html.escape(name)}: {html.escape(fmt(value))}</title></path>')
        parts.append(f'<text class="value" x="{label_w + w + 6:.1f}" y="{y + row / 2 + 4}">{html.escape(fmt(value))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _table(values: dict[str, float], fmt: Any, head: tuple[str, str]) -> str:
    rows = "".join(f'<tr><td>{html.escape(k)}</td><td class="num">{html.escape(fmt(v))}</td></tr>' for k, v in values.items())
    return (f"<details><summary>Table</summary><table><tr><th>{head[0]}</th><th>{head[1]}</th></tr>{rows}</table></details>"
            if values else "")


def _money(v: float | None) -> str:
    return "-" if v is None else f"${v:.4f}" if v < 1 else f"${v:,.2f}"


def _share(v: float | None) -> str:
    return "-" if v is None else f"{v:.0%}"


def page(d: dict[str, Any]) -> str:
    """Return the dashboard as one HTML page with no outside resources."""
    tiles = [("Answers", f"{d['answers']:,}"), (f"Spend ({d['priced']} priced)", _money(d["spend"])),
             (f"Rated good ({d['rated']} rated)", _share(d["good_rate"])), ("Escalated", _share(d["escalation_rate"])),
             ("Input from prompt cache", _share(d["cached_share"])), ("Kept on your machine", f"{d['private']:,}")]
    good = {f"{k} ({d['rated_per_kind'][k]})": v for k, v in d["good_rate_per_kind"].items()}
    cards = [
        ("Spend per day", _bars(d["spend_per_day"], _money), _table(d["spend_per_day"], _money, ("Day", "Spend"))),
        ("Answers per model", _bars(d["answers_per_model"], lambda v: f"{v:,.0f}"),
         _table(d["answers_per_model"], lambda v: f"{v:,.0f}", ("Model", "Answers"))),
        ("Rated good, per kind of task (ratings in brackets)", _bars(good, _share, 1.0), _table(good, _share, ("Kind", "Good"))),
        ("Answers per slot", _bars(d["answers_per_slot"], lambda v: f"{v:,.0f}"),
         _table(d["answers_per_slot"], lambda v: f"{v:,.0f}", ("Slot", "Answers"))),
    ]
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Crossvet chat: {html.escape(d['from'])} to {html.escape(d['to'])}</title><style>{CSS}</style></head><body>"
            f"<h1>Crossvet chat</h1><p class='sub'>{html.escape(d['from'])} to {html.escape(d['to'])} · counted from the local store</p>"
            "<div class='tiles'>" + "".join(f"<div class='tile'><div class='label'>{html.escape(k)}</div><div class='value'>"
                                             f"{html.escape(v)}</div></div>" for k, v in tiles) + "</div>"
            "<div class='grid'>" + "".join(f"<div class='card'><h2>{html.escape(t)}</h2>{chart}{table}</div>"
                                            for t, chart, table in cards) + "</div></body></html>\n")


__all__ = ["data", "page"]

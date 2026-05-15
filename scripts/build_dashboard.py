#!/usr/bin/env python3
"""
Build a static-HTML dashboard from `audit_history.py` SQLite database.

Why static, not a live server:
  - Zero hosting cost — open `index.html` from filesystem, or `python -m
    http.server`, or deploy to GitHub Pages / Netlify / S3 / any static host.
  - No daemon to babysit, no security surface beyond plain HTML.
  - Stays true to "skill that generates artifacts" identity — re-build on
    demand or via cron.

What's generated (output dir defaults to `./dashboard/`):

  dashboard/
  ├── index.html              — domains overview + global trends + top issues
  ├── style.css               — shared dark-theme CSS, self-contained
  ├── <domain>/
  │   ├── index.html          — per-domain trend, latest score, runs list
  │   └── run-<id>.html       — full report (uses render_html_report fmt)

Charts: inline SVG sparklines (no JS dependency, no CDN).

Re-run any time — overwrites previous build. Resume-safe (idempotent).

Usage:
  scripts/build_dashboard.py                       # uses default DB
  scripts/build_dashboard.py --output ./public     # custom output dir
  scripts/build_dashboard.py --db ~/audit.db       # custom DB

Then:
  open dashboard/index.html                         # local file
  tools/serve_dashboard.sh                          # localhost:8080
"""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def _db_path() -> Path:
    override = os.environ.get("AMAZING_SEO_HISTORY_DB")
    if override:
        return Path(override)
    return Path.home() / ".amazing-seo-skill" / "history.db"


_CSS = """
/* amazing-seo-skill dashboard — terminal minimal */
:root {
  --bg:       #0a0a0a;
  --bg-alt:   #111111;
  --fg:       #e4e4e4;
  --fg-dim:   #888;
  --muted:    #555;
  --border:   #1c1c1c;
  --border-hi:#2a2a2a;
  --accent:   #00d4aa;   /* mint — single accent, used sparingly */
  --good:     #00d4aa;
  --warn:     #ffb800;
  --bad:      #ff4757;
  --mono: 'JetBrains Mono', 'SF Mono', 'Cascadia Code', ui-monospace, Menlo, monospace;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0 auto; padding: 2.5rem 2rem; background: var(--bg); color: var(--fg);
  font-family: var(--mono); font-size: 13px; line-height: 1.6;
  letter-spacing: 0.01em; max-width: 1100px;
  font-feature-settings: "ss01", "cv02";
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--fg); }

/* Header — section banner */
header {
  border-bottom: 1px solid var(--border);
  padding-bottom: 1rem; margin-bottom: 2rem;
}
header .crumb {
  color: var(--muted); font-size: 12px; margin-bottom: 0.6rem;
  letter-spacing: 0.04em;
}
header .crumb a { color: var(--fg-dim); }
header .crumb a:hover { color: var(--accent); }
header h1 {
  margin: 0 0 0.3rem 0; font-weight: 500; font-size: 18px;
  letter-spacing: 0.02em;
}
header .url { color: var(--fg-dim); font-size: 12px; word-break: break-all; }
header .meta { color: var(--muted); font-size: 11px; margin-top: 0.5rem; letter-spacing: 0.05em; text-transform: uppercase; }

/* Section markers — ASCII style */
h2 {
  margin: 2.5rem 0 1rem 0;
  font-weight: 500; font-size: 12px;
  color: var(--fg-dim);
  text-transform: uppercase;
  letter-spacing: 0.15em;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}
h2::before { content: "» "; color: var(--accent); }
h3 {
  margin-top: 1.25rem; margin-bottom: 0.5rem; font-size: 12px; font-weight: 500;
  color: var(--fg-dim); text-transform: uppercase; letter-spacing: 0.1em;
}
.muted { color: var(--muted); font-size: 12px; }
.url { color: var(--fg-dim); }

/* Domain cards — list rows, not boxes */
.cards {
  display: flex; flex-direction: column;
  border-top: 1px solid var(--border);
}
.card {
  display: grid;
  grid-template-columns: 1fr auto 140px 100px;
  align-items: center; gap: 1.5rem;
  padding: 0.9rem 0.5rem;
  border-bottom: 1px solid var(--border);
  color: var(--fg);
}
.card:hover { background: var(--bg-alt); }
.card .domain-name { font-size: 14px; font-weight: 500; }
.card .score { font-size: 22px; font-weight: 500; font-variant-numeric: tabular-nums; text-align: right; }
.card .sparkline { display: flex; align-items: center; }
.card .meta { font-size: 11px; color: var(--muted); letter-spacing: 0.05em; text-align: right; }

table {
  width: 100%; border-collapse: collapse; margin: 0.5rem 0 1rem;
  font-size: 12px;
}
th {
  text-align: left; padding: 0.5rem 0.8rem 0.5rem 0;
  font-weight: 500; font-size: 10px;
  color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em;
  border-bottom: 1px solid var(--border);
}
td {
  padding: 0.55rem 0.8rem 0.55rem 0; border-bottom: 1px solid var(--border);
  vertical-align: top; font-variant-numeric: tabular-nums;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--bg-alt); }

.score-good { color: var(--good); }
.score-warn { color: var(--warn); }
.score-bad  { color: var(--bad); }

.delta-up   { color: var(--good); }
.delta-down { color: var(--bad); }
.delta-flat { color: var(--muted); }

/* Severity tokens — terminal label style */
.badge {
  display: inline-block; padding: 0.05rem 0.4rem;
  font-family: var(--mono); font-size: 10px; font-weight: 500;
  letter-spacing: 0.1em; border: 1px solid currentColor;
}
.badge-p0 { color: var(--bad); }
.badge-p1 { color: var(--warn); }
.badge-p2 { color: var(--fg-dim); }

.sev-p0 td:first-child { border-left: 2px solid var(--bad); padding-left: 0.6rem; }
.sev-p1 td:first-child { border-left: 2px solid var(--warn); padding-left: 0.6rem; }
.sev-p2 td:first-child { border-left: 2px solid var(--muted); padding-left: 0.6rem; }

/* Big status panel */
.score-card {
  display: grid; grid-template-columns: auto 1fr;
  gap: 2rem; align-items: center;
  border: 1px solid var(--border); padding: 1.25rem 1.5rem;
  margin-bottom: 2rem;
}
.score-gauge {
  font-size: 56px; font-weight: 400; line-height: 1;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
}
.score-detail { font-size: 12px; }
.score-detail .label {
  color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.12em; font-size: 10px; margin-bottom: 0.2rem;
}
.score-detail p { margin: 0.2rem 0; }

/* Category grid */
.cat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.5rem; margin-bottom: 1.5rem;
}
.cat-card {
  border: 1px solid var(--border); padding: 0.7rem 0.9rem;
}
.cat-name {
  color: var(--muted); font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.12em;
}
.cat-score {
  font-size: 22px; font-weight: 400; margin: 0.2rem 0;
  font-variant-numeric: tabular-nums;
}
.cat-checkers { font-size: 11px; color: var(--fg-dim); }

/* Trend block */
.trend-block {
  border: 1px solid var(--border); padding: 1rem 1.25rem; margin-bottom: 1.5rem;
}
.trend-block .meta { font-size: 11px; color: var(--muted); margin-top: 0.6rem;
  letter-spacing: 0.05em; }

footer {
  margin-top: 3.5rem; padding-top: 1rem;
  border-top: 1px solid var(--border);
  color: var(--muted); font-size: 10px;
  letter-spacing: 0.15em; text-transform: uppercase;
  text-align: left;
}
footer a { color: var(--fg-dim); }
footer a:hover { color: var(--accent); }

svg.sparkline { display: block; }
"""


def _score_class(s: int | float | None) -> str:
    if s is None: return ""
    if s >= 80: return "score-good"
    if s >= 60: return "score-warn"
    return "score-bad"


def _emoji(s: int | float | None) -> str:
    # Kept for API compatibility but returns empty — terminal aesthetic
    return ""


def _status(s: int | float | None) -> str:
    """Text status label — replaces emoji."""
    if s is None: return "n/a"
    if s >= 80: return "ok"
    if s >= 60: return "warn"
    return "fail"


def _delta_html(delta: int | None) -> str:
    if delta is None:
        return ""
    if delta == 0:
        return "<span class='delta-flat'>±0</span>"
    if delta > 0:
        return f"<span class='delta-up'>+{delta}</span>"
    return f"<span class='delta-down'>{delta}</span>"


def _sparkline(values: list[int], width: int = 140, height: int = 32,
                color: str = "#00d4aa") -> str:
    """Tiny inline SVG sparkline. Mint accent dot at the latest point."""
    if not values:
        return ""
    if len(values) == 1:
        values = values * 2
    vmin, vmax = min(values), max(values)
    rng = max(1, vmax - vmin)
    step = width / (len(values) - 1) if len(values) > 1 else width
    pts = []
    for i, v in enumerate(values):
        x = i * step
        y = height - ((v - vmin) / rng) * (height - 6) - 3
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    last_x = (len(values) - 1) * step
    last_y = height - ((values[-1] - vmin) / rng) * (height - 6) - 3
    return (
        f'<svg class="sparkline" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline points="{polyline}" fill="none" stroke="#555" stroke-width="1"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2" fill="{color}"/>'
        f'</svg>'
    )


def _domain_slug(url: str) -> str:
    """URL → safe directory name."""
    host = urlparse(url).hostname or "unknown"
    return host.replace(":", "_")


def _render_index(domains_data: list[dict], conn: sqlite3.Connection,
                   build_ts: str) -> str:
    """Build dashboard/index.html — overview of all domains."""
    total_runs = sum(d["run_count"] for d in domains_data)

    domain_rows = []
    for d in domains_data:
        score = d["latest_score"]
        score_class = _score_class(score)
        sparkline = _sparkline([r["score"] for r in d["recent_runs"]])
        delta = (
            d["recent_runs"][-1]["score"] - d["recent_runs"][-2]["score"]
            if len(d["recent_runs"]) >= 2 else None
        )
        hostname = urlparse(d['url']).hostname or d['url']
        # Last-seen relative
        try:
            last_dt = datetime.fromisoformat(d['last_ts'].replace("Z","+00:00"))
            ago_s = (datetime.now(timezone.utc) - last_dt).total_seconds()
            ago = (f"{int(ago_s // 86400)}d" if ago_s >= 86400 else
                   f"{int(ago_s // 3600)}h" if ago_s >= 3600 else
                   f"{int(ago_s // 60)}m")
        except Exception:
            ago = d['last_ts']
        domain_rows.append(f"""
        <a class="card" href="{html.escape(d['slug'])}/index.html">
          <span class="domain-name">{html.escape(hostname)}</span>
          <span class="score {score_class}">{score}</span>
          {sparkline}
          <span class="meta">{_delta_html(delta) or '·'} &nbsp; {ago} &nbsp; {d['run_count']}r</span>
        </a>""")

    # Top recurring P0/P1 issues across all domains
    findings = conn.execute("""
        SELECT severity, checker, text, COUNT(DISTINCT runs.url) AS domains, COUNT(*) AS total
        FROM findings JOIN runs ON findings.run_id = runs.id
        WHERE severity IN ('P0', 'P1')
        GROUP BY severity, checker, text
        ORDER BY domains DESC, total DESC
        LIMIT 15
    """).fetchall()
    findings_rows = "\n".join(
        f"<tr class='sev-{sev.lower()}'>"
        f"<td><span class='badge badge-{sev.lower()}'>{sev}</span></td>"
        f"<td>{html.escape(ck)}</td>"
        f"<td>{html.escape(text)}</td>"
        f"<td>{n_domains}</td>"
        f"<td>{n_total}</td></tr>"
        for sev, ck, text, n_domains, n_total in findings
    ) or "<tr><td colspan='5' class='muted'>no P0/P1 findings recorded</td></tr>"

    empty_msg = "<p class='muted'>no audits stored. run <code>page_score.py --format json &lt;url&gt; | audit_history.py store -</code></p>"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>amazing-seo-skill / dashboard</title>
<link rel="stylesheet" href="style.css">
</head><body>
<header>
  <div class="crumb">amazing-seo-skill / dashboard</div>
  <h1>system overview</h1>
  <div class="meta">{len(domains_data)} domains · {total_runs} runs · {build_ts}</div>
</header>

<h2>domains</h2>
<div class="cards">{"".join(domain_rows) or empty_msg}</div>

<h2>recurring issues — p0/p1, all domains</h2>
<table>
  <thead><tr><th>sev</th><th>checker</th><th>issue</th><th>domains</th><th>runs</th></tr></thead>
  <tbody>{findings_rows}</tbody>
</table>

<footer>
  amazing-seo-skill · <a href="https://github.com/metawhisp/amazing-seo-skill">github</a>
</footer>
</body></html>"""


def _render_domain(domain_url: str, runs: list[dict], conn: sqlite3.Connection,
                    build_ts: str) -> str:
    """Build dashboard/<slug>/index.html — per-domain page."""
    slug = _domain_slug(domain_url)
    latest = runs[-1] if runs else None
    if not latest:
        return ""

    scores = [r["score"] for r in runs]
    big_spark = _sparkline(scores, width=600, height=120)

    # Runs table
    rows = []
    prev = None
    for r in reversed(runs):  # latest first
        delta = (r["score"] - prev) if prev is not None else None
        rows.append(f"""<tr>
            <td><a href="run-{r['id']}.html">{r['ts']}</a></td>
            <td class="{_score_class(r['score'])}">{r['score']}</td>
            <td>{_delta_html(delta) if delta is not None else ''}</td>
          </tr>""")
        # delta in reverse: compare to "next older" run is needed
        # Above gives wrong delta direction; fix:
    # Recompute delta in correct order (chronological)
    rows = []
    sorted_runs = sorted(runs, key=lambda r: r["ts"])
    prev_score = None
    for r in sorted_runs:
        delta = (r["score"] - prev_score) if prev_score is not None else None
        rows.append((r, delta))
        prev_score = r["score"]
    # Display newest first
    rows_html = "\n".join(
        f"""<tr>
            <td><a href="run-{r['id']}.html">{r['ts']}</a></td>
            <td class="{_score_class(r['score'])}" style="text-align:right">{r['score']}</td>
            <td>{_delta_html(delta) if delta is not None else ''}</td>
          </tr>"""
        for r, delta in reversed(rows)
    )

    # Latest run findings
    findings = conn.execute("""
        SELECT severity, checker, text FROM findings WHERE run_id=?
    """, (latest["id"],)).fetchall()
    findings_by_sev: dict[str, list] = {"P0": [], "P1": [], "P2": []}
    for sev, ck, text in findings:
        findings_by_sev.setdefault(sev, []).append((ck, text))

    findings_html = []
    for sev, label in [("P0", "Critical"), ("P1", "High"), ("P2", "Medium")]:
        items = findings_by_sev.get(sev, [])
        if not items:
            continue
        rows_ = "\n".join(
            f"<tr class='sev-{sev.lower()}'>"
            f"<td><span class='badge badge-{sev.lower()}'>{sev}</span></td>"
            f"<td>{html.escape(ck)}</td>"
            f"<td>{html.escape(text)}</td></tr>"
            for ck, text in items
        )
        findings_html.append(f"""
          <h3>{label.lower()} — {len(items)}</h3>
          <table><thead><tr><th>sev</th><th>checker</th><th>issue</th></tr></thead>
          <tbody>{rows_}</tbody></table>""")

    hostname = urlparse(domain_url).hostname or domain_url
    p0_n = len(findings_by_sev.get('P0', []))
    p1_n = len(findings_by_sev.get('P1', []))
    p2_n = len(findings_by_sev.get('P2', []))
    score_cls = _score_class(latest['score'])

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(hostname)} / dashboard</title>
<link rel="stylesheet" href="../style.css">
</head><body>
<header>
  <div class="crumb"><a href="../index.html">‹ all domains</a> / {html.escape(hostname)}</div>
  <h1>{html.escape(hostname)}</h1>
  <div class="url">{html.escape(domain_url)}</div>
  <div class="meta">{len(runs)} runs · last {latest['ts']}</div>
</header>

<div class="score-card">
  <div class="score-gauge {score_cls}">{latest['score']}</div>
  <div class="score-detail">
    <div class="label">health score</div>
    <p style="font-size:14px; margin-top: 0.3rem;">status: <span class="{score_cls}">{_status(latest['score'])}</span></p>
    <p class="muted">{len(findings)} findings · {p0_n} p0 · {p1_n} p1 · {p2_n} p2</p>
  </div>
</div>

<h2>score trend</h2>
<div class="trend-block">
  {big_spark}
  <div class="meta">range {min(scores)}–{max(scores)} · mean {sum(scores)//len(scores)} · {len(runs)} runs</div>
</div>

<h2>runs</h2>
<table>
  <thead><tr><th>timestamp</th><th style="text-align:right">score</th><th>Δ</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>

<h2>latest findings</h2>
{"".join(findings_html) or "<p class='muted'>no findings in latest run</p>"}

<footer>
  amazing-seo-skill · <a href="https://github.com/metawhisp/amazing-seo-skill">github</a>
</footer>
</body></html>"""


def _render_run(run: dict, payload: dict, conn: sqlite3.Connection) -> str:
    """Full per-run report — re-use render_html_report's layout."""
    summary = payload.get("summary", {})
    score = summary.get("health_score", run["score"])
    score_cls = _score_class(score)
    by_cat = summary.get("by_category", {})
    findings = summary.get("all_findings", [])

    findings_by_sev: dict[str, list] = {"P0": [], "P1": [], "P2": []}
    for f in findings:
        findings_by_sev.setdefault(f["severity"], []).append(f)

    sev_html = []
    for sev, label in [("P0", "critical"), ("P1", "high"), ("P2", "medium")]:
        items = findings_by_sev.get(sev, [])
        if not items:
            continue
        rows = "\n".join(
            f"<tr class='sev-{sev.lower()}'>"
            f"<td><span class='badge badge-{sev.lower()}'>{sev}</span></td>"
            f"<td>{html.escape(f.get('checker','?'))}</td>"
            f"<td>{html.escape(f.get('text',''))}</td></tr>"
            for f in items
        )
        sev_html.append(f"<h3>{label} — {len(items)}</h3>"
                        f"<table><thead><tr><th>sev</th><th>checker</th><th>issue</th></tr></thead>"
                        f"<tbody>{rows}</tbody></table>")

    cat_cards = []
    for cat, agg in sorted(by_cat.items()):
        s = agg.get("score")
        checkers = ", ".join(
            f"{c['key']} {c.get('sub_score','—')}"
            for c in agg.get("checkers", []) if not c.get("skipped")
        ) or "—"
        cat_cards.append(f"""<div class="cat-card">
          <div class="cat-name">{html.escape(cat)}</div>
          <div class="cat-score {_score_class(s)}">{s if s is not None else '—'}</div>
          <div class="cat-checkers">{html.escape(checkers)}</div>
        </div>""")

    hostname = urlparse(run['url']).hostname or run['url']
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>run #{run['id']} / {html.escape(hostname)}</title>
<link rel="stylesheet" href="../style.css">
</head><body>
<header>
  <div class="crumb"><a href="../index.html">‹ domains</a> / <a href="index.html">{html.escape(hostname)}</a> / run #{run['id']}</div>
  <h1>run #{run['id']}</h1>
  <div class="url">{html.escape(run['url'])}</div>
  <div class="meta">{run['ts']}</div>
</header>

<div class="score-card">
  <div class="score-gauge {score_cls}">{score}</div>
  <div class="score-detail">
    <div class="label">health score</div>
    <p style="font-size:14px;">status: <span class="{score_cls}">{_status(score)}</span></p>
    <p class="muted">based on {summary.get('active_weight_pct', 0)}% of weight</p>
  </div>
</div>

<h2>category scores</h2>
<div class="cat-grid">{"".join(cat_cards)}</div>

<h2>findings</h2>
{"".join(sev_html) or "<p class='muted'>no findings</p>"}

<footer>amazing-seo-skill · <a href="https://github.com/metawhisp/amazing-seo-skill">github</a></footer>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", help="path to history.db (default: ~/.amazing-seo-skill/history.db)")
    ap.add_argument("--output", default="dashboard", help="output directory (default: ./dashboard)")
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else _db_path()
    if not db_path.exists():
        print(f"ERROR: no history DB at {db_path}", file=sys.stderr)
        print("  Run: page_score.py --format json <url> | audit_history.py store -", file=sys.stderr)
        return 1

    out_dir = Path(args.output)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    build_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Gather domains
    domains = conn.execute(
        "SELECT url, COUNT(*) AS run_count, MAX(ts) AS last_ts FROM runs GROUP BY url ORDER BY last_ts DESC"
    ).fetchall()

    domains_data = []
    for d in domains:
        url = d["url"]
        runs = conn.execute(
            "SELECT id, ts, score, payload FROM runs WHERE url=? ORDER BY ts ASC", (url,),
        ).fetchall()
        runs_list = [{"id": r["id"], "ts": r["ts"], "score": r["score"], "payload": r["payload"]}
                     for r in runs]
        slug = _domain_slug(url)
        domains_data.append({
            "url": url, "slug": slug, "run_count": d["run_count"],
            "last_ts": d["last_ts"], "latest_score": runs_list[-1]["score"],
            "recent_runs": runs_list[-30:],   # cap sparkline data
            "all_runs": runs_list,
        })

    # Write style.css
    (out_dir / "style.css").write_text(_CSS, encoding="utf-8")

    # Write index
    (out_dir / "index.html").write_text(
        _render_index(domains_data, conn, build_ts), encoding="utf-8"
    )

    # Per-domain
    for d in domains_data:
        domain_dir = out_dir / d["slug"]
        domain_dir.mkdir(parents=True, exist_ok=True)
        (domain_dir / "index.html").write_text(
            _render_domain(d["url"], d["all_runs"], conn, build_ts),
            encoding="utf-8",
        )
        for r in d["all_runs"]:
            try:
                payload = json.loads(r["payload"]) if r["payload"] else {}
            except json.JSONDecodeError:
                payload = {}
            (domain_dir / f"run-{r['id']}.html").write_text(
                _render_run(
                    {"id": r["id"], "ts": r["ts"], "score": r["score"], "url": d["url"]},
                    payload, conn,
                ),
                encoding="utf-8",
            )

    conn.close()
    print(json.dumps({
        "output_dir": str(out_dir.resolve()),
        "domains": len(domains_data),
        "total_runs": sum(d["run_count"] for d in domains_data),
        "index": str((out_dir / "index.html").resolve()),
        "next_steps": [
            f"open file://{(out_dir / 'index.html').resolve()}",
            "or: tools/serve_dashboard.sh   (starts http.server on :8080)",
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

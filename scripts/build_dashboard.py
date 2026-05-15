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
:root {
  --bg: #0f1419; --fg: #e6e6e6; --muted: #8a8a8a; --card: #1a1f2e;
  --border: #2a3142; --accent: #4a9eff;
  --green: #4ade80; --yellow: #facc15; --red: #f87171; --orange: #fb923c;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  --mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem; background: var(--bg); color: var(--fg);
  font-family: var(--font); line-height: 1.5; font-size: 15px;
  max-width: 1200px; margin: 0 auto;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header { border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 2rem; }
h1 { margin: 0 0 0.5rem 0; font-weight: 600; font-size: 1.8rem; }
h2 { margin-top: 2.5rem; margin-bottom: 1rem; font-size: 1.25rem;
     border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; font-weight: 600; }
h3 { margin-top: 1.5rem; margin-bottom: 0.75rem; font-size: 1.05rem; }
.muted { color: var(--muted); font-size: 0.875rem; }
.url { font-family: var(--mono); color: var(--accent); word-break: break-all; }

.cards {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem; margin-bottom: 1.5rem;
}
.card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; padding: 1rem 1.25rem;
}
.card h3 { margin: 0 0 0.5rem 0; font-size: 1rem; }
.card .score { font-size: 2.5rem; font-weight: 700; line-height: 1; }
.card .meta { color: var(--muted); font-size: 0.85rem; margin-top: 0.5rem; }
.card .sparkline { margin-top: 0.5rem; }

table { width: 100%; border-collapse: collapse; margin: 1rem 0;
        background: var(--card); border: 1px solid var(--border); border-radius: 8px;
        overflow: hidden; }
th { background: rgba(255,255,255,0.04); text-align: left;
     padding: 0.6rem 0.9rem; font-weight: 600; font-size: 0.85rem;
     color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;
     border-bottom: 1px solid var(--border); }
td { padding: 0.6rem 0.9rem; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255,255,255,0.03); }

.score-good { color: var(--green); }
.score-warn { color: var(--yellow); }
.score-bad  { color: var(--red); }

.delta-up   { color: var(--green); }
.delta-down { color: var(--red); }
.delta-flat { color: var(--muted); }

.badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px;
         font-family: var(--mono); font-size: 0.75rem; font-weight: 600; }
.badge-p0 { background: rgba(248,113,113,0.15); color: var(--red); }
.badge-p1 { background: rgba(251,146,60,0.15); color: var(--orange); }
.badge-p2 { background: rgba(250,204,21,0.12); color: var(--yellow); }

.sev-p0 { background: rgba(248,113,113,0.08); border-left: 3px solid var(--red); }
.sev-p1 { background: rgba(251,146,60,0.06); border-left: 3px solid var(--orange); }
.sev-p2 { background: rgba(250,204,21,0.04); border-left: 3px solid var(--yellow); }

.score-card {
  display: flex; gap: 2rem; align-items: center;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 1.5rem 2rem; margin-bottom: 2rem;
}
.score-gauge { font-size: 4rem; font-weight: 700; line-height: 1; }
.score-detail { flex: 1; }

.cat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem; margin-bottom: 1.5rem;
}
.cat-card { background: var(--card); border: 1px solid var(--border);
            border-radius: 8px; padding: 0.75rem 1rem; }
.cat-name { color: var(--muted); font-size: 0.85rem; text-transform: uppercase;
            letter-spacing: 0.5px; }
.cat-score { font-size: 1.5rem; font-weight: 600; margin: 0.25rem 0; }
.cat-checkers { font-size: 0.8rem; color: var(--muted); }

footer { margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--border);
         color: var(--muted); font-size: 0.85rem; text-align: center; }

svg.sparkline { display: block; }
"""


def _score_class(s: int | float | None) -> str:
    if s is None: return ""
    if s >= 80: return "score-good"
    if s >= 60: return "score-warn"
    return "score-bad"


def _emoji(s: int | float | None) -> str:
    if s is None: return "—"
    if s >= 80: return "🟢"
    if s >= 60: return "🟡"
    return "🔴"


def _delta_html(delta: int | None) -> str:
    if delta is None or delta == 0:
        return "<span class='delta-flat'>→</span>"
    if delta > 0:
        return f"<span class='delta-up'>▲ +{delta}</span>"
    return f"<span class='delta-down'>▼ {delta}</span>"


def _sparkline(values: list[int], width: int = 140, height: int = 36) -> str:
    """Tiny inline SVG sparkline with last-point dot."""
    if not values:
        return ""
    if len(values) == 1:
        values = values * 2  # need at least 2 points for a line
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
        f'<polyline points="{polyline}" fill="none" stroke="#4a9eff" stroke-width="1.5"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.5" fill="#4a9eff"/>'
        f'</svg>'
    )


def _domain_slug(url: str) -> str:
    """URL → safe directory name."""
    host = urlparse(url).hostname or "unknown"
    return host.replace(":", "_")


def _render_index(domains_data: list[dict], conn: sqlite3.Connection,
                   build_ts: str) -> str:
    """Build dashboard/index.html — overview of all domains."""
    domain_cards = []
    for d in domains_data:
        score = d["latest_score"]
        score_class = _score_class(score)
        sparkline = _sparkline([r["score"] for r in d["recent_runs"]])
        delta = (
            d["recent_runs"][-1]["score"] - d["recent_runs"][-2]["score"]
            if len(d["recent_runs"]) >= 2 else None
        )
        domain_cards.append(f"""
        <a class="card" href="{html.escape(d['slug'])}/index.html" style="text-decoration:none;color:inherit;display:block;">
          <h3>{_emoji(score)} {html.escape(urlparse(d['url']).hostname or d['url'])}</h3>
          <div class="score {score_class}">{score}</div>
          {sparkline}
          <div class="meta">
            {len(d['recent_runs'])} runs · {_delta_html(delta)} · last {d['last_ts']}
          </div>
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
        f"<td><code>{html.escape(ck)}</code></td>"
        f"<td>{html.escape(text)}</td>"
        f"<td>{n_domains}</td>"
        f"<td>{n_total}</td></tr>"
        for sev, ck, text, n_domains, n_total in findings
    ) or "<tr><td colspan='5' class='muted'>No P0/P1 findings recorded.</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>amazing-seo-skill — Dashboard</title>
<link rel="stylesheet" href="style.css">
</head><body>
<header>
  <h1>🟢 amazing-seo-skill — Dashboard</h1>
  <p class="muted">{len(domains_data)} domain(s) tracked · Generated {build_ts}</p>
</header>

<h2>Domains</h2>
<div class="cards">{"".join(domain_cards) or "<p class='muted'>No audits stored yet. Run <code>page_score.py --format json &lt;url&gt; | audit_history.py store -</code> first.</p>"}</div>

<h2>Top recurring issues (P0/P1, across all domains)</h2>
<table>
  <thead><tr><th>Severity</th><th>Checker</th><th>Issue</th><th>Domains</th><th>Total runs</th></tr></thead>
  <tbody>{findings_rows}</tbody>
</table>

<footer>
  Generated by <a href="https://github.com/metawhisp/amazing-seo-skill">amazing-seo-skill</a>
  <code>build_dashboard.py</code> · {build_ts}
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
            <td class="{_score_class(r['score'])}">{r['score']}</td>
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
            f"<td><code>{html.escape(ck)}</code></td>"
            f"<td>{html.escape(text)}</td></tr>"
            for ck, text in items
        )
        findings_html.append(f"""
          <h3>{sev} — {label} ({len(items)})</h3>
          <table><thead><tr><th>Sev</th><th>Checker</th><th>Issue</th></tr></thead>
          <tbody>{rows_}</tbody></table>""")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(domain_url)} — Dashboard</title>
<link rel="stylesheet" href="../style.css">
</head><body>
<header>
  <p><a href="../index.html">← All domains</a></p>
  <h1>{_emoji(latest['score'])} {html.escape(urlparse(domain_url).hostname or domain_url)}</h1>
  <p class="url">{html.escape(domain_url)}</p>
  <p class="muted">{len(runs)} runs · Generated {build_ts}</p>
</header>

<div class="score-card">
  <div class="score-gauge {_score_class(latest['score'])}">{latest['score']}</div>
  <div class="score-detail">
    <p style="font-size:1.1rem;">Latest Health Score (out of <strong>100</strong>)</p>
    <p class="muted">Last run: {latest['ts']}</p>
    <p class="muted">{len(findings)} findings · {len(findings_by_sev.get('P0',[]))} critical, {len(findings_by_sev.get('P1',[]))} high, {len(findings_by_sev.get('P2',[]))} medium</p>
  </div>
</div>

<h2>Score trend</h2>
<div class="card">{big_spark}<p class="muted" style="margin-top:0.5rem">Range: {min(scores)} – {max(scores)} · Mean: {sum(scores)//len(scores)}</p></div>

<h2>All runs</h2>
<table>
  <thead><tr><th>Timestamp</th><th>Score</th><th>Δ vs prev</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>

<h2>Findings from latest run</h2>
{"".join(findings_html) or "<p class='muted'>No findings in latest run.</p>"}

<footer>
  Generated by <a href="https://github.com/metawhisp/amazing-seo-skill">amazing-seo-skill</a>
  · {build_ts}
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
    for sev, label in [("P0", "Critical"), ("P1", "High"), ("P2", "Medium")]:
        items = findings_by_sev.get(sev, [])
        if not items:
            continue
        rows = "\n".join(
            f"<tr class='sev-{sev.lower()}'>"
            f"<td><span class='badge badge-{sev.lower()}'>{sev}</span></td>"
            f"<td><code>{html.escape(f.get('checker','?'))}</code></td>"
            f"<td>{html.escape(f.get('text',''))}</td></tr>"
            for f in items
        )
        sev_html.append(f"<h3>{sev} — {label} ({len(items)})</h3>"
                        f"<table><thead><tr><th>Sev</th><th>Checker</th><th>Issue</th></tr></thead>"
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

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Run {run['id']} — {html.escape(run['url'])}</title>
<link rel="stylesheet" href="../style.css">
</head><body>
<header>
  <p><a href="index.html">← Domain</a> · <a href="../index.html">All domains</a></p>
  <h1>Run #{run['id']}</h1>
  <p class="url">{html.escape(run['url'])}</p>
  <p class="muted">{run['ts']}</p>
</header>

<div class="score-card">
  <div class="score-gauge {score_cls}">{_emoji(score)} {score}</div>
  <div class="score-detail">
    <p style="font-size:1.1rem;">out of <strong>100</strong></p>
    <p class="muted">Based on {summary.get('active_weight_pct', 0)}% of weight</p>
  </div>
</div>

<h2>Score by category</h2>
<div class="cat-grid">{"".join(cat_cards)}</div>

<h2>Findings</h2>
{"".join(sev_html) or "<p class='muted'>No findings.</p>"}

<footer>Generated by <a href="https://github.com/metawhisp/amazing-seo-skill">amazing-seo-skill</a></footer>
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

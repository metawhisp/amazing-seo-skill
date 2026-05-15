#!/usr/bin/env python3
"""
Render a `page_score.py --format json` (or `site_audit.sh` JSON) into a
shareable styled HTML report.

Why HTML, not just Markdown:
  - Stakeholder reports need to render in a browser without a Markdown
    viewer.
  - Visual hierarchy (color-coded severity, score gauge, category cards)
    communicates priorities faster than monospace text.
  - Single self-contained file — no external CSS, fonts, or JS — so it
    can be emailed, attached, or hosted anywhere.

Input: JSON produced by `page_score.py --format json` (single page) or
`site_audit.sh` (multi-page). Auto-detects shape.

Usage:
  scripts/page_score.py https://example.com --format json | \
    scripts/render_html_report.py > REPORT.html

  scripts/render_html_report.py audit.json > REPORT.html
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone


_CSS = """
/* amazing-seo-skill report — terminal minimal */
:root {
  --bg:       #0a0a0a;
  --bg-alt:   #111111;
  --fg:       #e4e4e4;
  --fg-dim:   #888;
  --muted:    #555;
  --border:   #1c1c1c;
  --accent:   #00d4aa;
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

header { border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 2rem; }
header .crumb { color: var(--muted); font-size: 12px; margin-bottom: 0.6rem; letter-spacing: 0.04em; }
header h1 { margin: 0 0 0.3rem 0; font-weight: 500; font-size: 18px; letter-spacing: 0.02em; }
header .url { color: var(--fg-dim); font-size: 12px; word-break: break-all; }
header .meta { color: var(--muted); font-size: 11px; margin-top: 0.5rem; letter-spacing: 0.05em; text-transform: uppercase; }

h2 {
  margin: 2.5rem 0 1rem 0; font-weight: 500; font-size: 12px;
  color: var(--fg-dim); text-transform: uppercase; letter-spacing: 0.15em;
  padding-bottom: 0.5rem; border-bottom: 1px solid var(--border);
}
h2::before { content: "» "; color: var(--accent); }
h3 {
  margin-top: 1.25rem; margin-bottom: 0.5rem; font-size: 12px; font-weight: 500;
  color: var(--fg-dim); text-transform: uppercase; letter-spacing: 0.1em;
}
.url { color: var(--fg-dim); }
.muted { color: var(--muted); font-size: 12px; }

.score-card {
  display: grid; grid-template-columns: auto 1fr;
  gap: 2rem; align-items: center;
  border: 1px solid var(--border); padding: 1.25rem 1.5rem; margin-bottom: 2rem;
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

.cat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.5rem; margin-bottom: 1.5rem;
}
.cat-card { border: 1px solid var(--border); padding: 0.7rem 0.9rem; }
.cat-name { color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.12em; }
.cat-score { font-size: 22px; font-weight: 400; margin: 0.2rem 0; font-variant-numeric: tabular-nums; }
.cat-checkers { font-size: 11px; color: var(--fg-dim); }

table { width: 100%; border-collapse: collapse; margin: 0.5rem 0 1rem; font-size: 12px; }
th {
  text-align: left; padding: 0.5rem 0.8rem 0.5rem 0;
  font-weight: 500; font-size: 10px;
  color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em;
  border-bottom: 1px solid var(--border);
}
td { padding: 0.55rem 0.8rem 0.55rem 0; border-bottom: 1px solid var(--border); vertical-align: top; font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: none; }

.sev-p0 td:first-child { border-left: 2px solid var(--bad); padding-left: 0.6rem; }
.sev-p1 td:first-child { border-left: 2px solid var(--warn); padding-left: 0.6rem; }
.sev-p2 td:first-child { border-left: 2px solid var(--muted); padding-left: 0.6rem; }

.badge {
  display: inline-block; padding: 0.05rem 0.4rem;
  font-family: var(--mono); font-size: 10px; font-weight: 500;
  letter-spacing: 0.1em; border: 1px solid currentColor;
}
.badge-p0 { color: var(--bad); }
.badge-p1 { color: var(--warn); }
.badge-p2 { color: var(--fg-dim); }

.score-good { color: var(--good); }
.score-warn { color: var(--warn); }
.score-bad  { color: var(--bad); }

footer {
  margin-top: 3.5rem; padding-top: 1rem; border-top: 1px solid var(--border);
  color: var(--muted); font-size: 10px;
  letter-spacing: 0.15em; text-transform: uppercase; text-align: left;
}
footer a { color: var(--fg-dim); }
footer a:hover { color: var(--accent); }
"""


def _score_class(s: int | float) -> str:
    if s is None:
        return "muted"
    if s >= 80: return "score-good"
    if s >= 60: return "score-warn"
    return "score-bad"


def _status(s: int | float | None) -> str:
    if s is None: return "n/a"
    if s >= 80: return "ok"
    if s >= 60: return "warn"
    return "fail"


def _render_page(data: dict) -> str:
    target = data.get("target", "?")
    summary = data.get("summary", {})
    score = summary.get("health_score", 0)
    score_cls = _score_class(score)
    by_cat = summary.get("by_category", {})
    findings = summary.get("all_findings", [])

    findings_by_sev = {"P0": [], "P1": [], "P2": []}
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
        sev_html.append(f"""
        <h3>{label} — {len(items)}</h3>
        <table>
          <thead><tr><th>sev</th><th>checker</th><th>issue</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>""")

    cat_cards = []
    for cat, agg in sorted(by_cat.items()):
        s = agg.get("score")
        checkers = ", ".join(
            f"{c['key']} {c.get('sub_score','—')}"
            for c in agg.get("checkers", []) if not c.get("skipped")
        ) or "—"
        cat_cards.append(f"""
        <div class='cat-card'>
          <div class='cat-name'>{html.escape(cat)}</div>
          <div class='cat-score {_score_class(s)}'>{s if s is not None else '—'}</div>
          <div class='cat-checkers'>{html.escape(checkers)}</div>
        </div>""")

    return f"""<!DOCTYPE html>
<html lang='en'><head><meta charset='utf-8'>
<title>{html.escape(target)} / page report</title>
<style>{_CSS}</style></head><body>
<header>
  <div class="crumb">amazing-seo-skill / page report</div>
  <h1>page audit</h1>
  <div class='url'>{html.escape(target)}</div>
  <div class='meta'>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>
</header>

<div class='score-card'>
  <div class='score-gauge {score_cls}'>{score}</div>
  <div class='score-detail'>
    <div class='label'>health score</div>
    <p style="font-size:14px;">status: <span class="{score_cls}">{_status(score)}</span></p>
    <p class='muted'>based on {summary.get('active_weight_pct', 0)}% of weight</p>
    <p class='muted'>{len(findings)} findings · {len(findings_by_sev.get('P0',[]))} p0 · {len(findings_by_sev.get('P1',[]))} p1 · {len(findings_by_sev.get('P2',[]))} p2</p>
  </div>
</div>

<h2>category scores</h2>
<div class='cat-grid'>{"".join(cat_cards)}</div>

<h2>findings</h2>
{"".join(sev_html) or "<p class='muted'>no findings — page is clean</p>"}

<footer>amazing-seo-skill · <a href='https://github.com/metawhisp/amazing-seo-skill'>github</a></footer>
</body></html>"""


def _render_site(data: dict) -> str:
    """For site_audit JSON: not implemented yet; redirect users to MD report."""
    # site_audit.sh already emits Markdown directly. We could re-parse it, but
    # for now keep this single-page focused.
    return f"""<!DOCTYPE html>
<html><head><title>Site Audit Report</title></head><body>
<p>Site-level audits emit Markdown directly via <code>tools/site_audit.sh</code>.
To render the per-page reports as HTML, run <code>page_score.py --format json
&lt;url&gt; | render_html_report.py</code> for each URL.</p>
<pre>{html.escape(json.dumps(data, indent=2))[:5000]}</pre>
</body></html>"""


def main() -> int:
    if len(sys.argv) == 2:
        with open(sys.argv[1]) as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    # Detect shape
    if isinstance(payload, dict) and "summary" in payload and "target" in payload:
        sys.stdout.write(_render_page(payload))
    else:
        sys.stdout.write(_render_site(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())

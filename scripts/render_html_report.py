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
  max-width: 1100px; margin: 0 auto;
}
header { border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 2rem; }
h1 { margin: 0 0 0.5rem 0; font-weight: 600; font-size: 1.8rem; }
h2 { margin-top: 2.5rem; margin-bottom: 1rem; font-size: 1.25rem;
     border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; font-weight: 600; }
h3 { margin-top: 1.5rem; margin-bottom: 0.75rem; font-size: 1.05rem; }
.url { font-family: var(--mono); color: var(--accent); word-break: break-all; }
.muted { color: var(--muted); font-size: 0.875rem; }

.score-card {
  display: flex; gap: 2rem; align-items: center;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; padding: 1.5rem 2rem; margin-bottom: 2rem;
}
.score-gauge { font-size: 4rem; font-weight: 700; line-height: 1; }
.score-detail { flex: 1; }
.score-detail p { margin: 0.25rem 0; }

.cat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.75rem; margin-bottom: 1.5rem;
}
.cat-card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 0.75rem 1rem;
}
.cat-name { color: var(--muted); font-size: 0.85rem; text-transform: uppercase;
            letter-spacing: 0.5px; }
.cat-score { font-size: 1.5rem; font-weight: 600; margin: 0.25rem 0; }
.cat-checkers { font-size: 0.8rem; color: var(--muted); }

table { width: 100%; border-collapse: collapse; margin: 1rem 0;
        background: var(--card); border: 1px solid var(--border); border-radius: 8px;
        overflow: hidden; }
th { background: rgba(255,255,255,0.04); text-align: left;
     padding: 0.6rem 0.9rem; font-weight: 600; font-size: 0.85rem;
     color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;
     border-bottom: 1px solid var(--border); }
td { padding: 0.6rem 0.9rem; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:last-child td { border-bottom: none; }

.sev-p0 { background: rgba(248,113,113,0.08); border-left: 3px solid var(--red); }
.sev-p1 { background: rgba(251,146,60,0.06); border-left: 3px solid var(--orange); }
.sev-p2 { background: rgba(250,204,21,0.04); border-left: 3px solid var(--yellow); }

.badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px;
         font-family: var(--mono); font-size: 0.75rem; font-weight: 600; }
.badge-p0 { background: rgba(248,113,113,0.15); color: var(--red); }
.badge-p1 { background: rgba(251,146,60,0.15); color: var(--orange); }
.badge-p2 { background: rgba(250,204,21,0.12); color: var(--yellow); }

.score-good { color: var(--green); }
.score-warn { color: var(--yellow); }
.score-bad  { color: var(--red); }

footer { margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--border);
         color: var(--muted); font-size: 0.85rem; text-align: center; }
"""


def _score_class(s: int | float) -> str:
    if s is None:
        return "muted"
    if s >= 80: return "score-good"
    if s >= 60: return "score-warn"
    return "score-bad"


def _emoji(s: int | float) -> str:
    if s is None:
        return "—"
    if s >= 80: return "🟢"
    if s >= 60: return "🟡"
    return "🔴"


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
    for sev, label, desc in [
        ("P0", "Critical", "Blocks indexing or causes penalties"),
        ("P1", "High", "Significantly impacts rankings"),
        ("P2", "Medium", "Optimization opportunity"),
    ]:
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
        sev_html.append(f"""
        <h3>{sev} — {label} ({len(items)})</h3>
        <p class='muted'>{desc}</p>
        <table>
          <thead><tr><th>Severity</th><th>Checker</th><th>Issue</th></tr></thead>
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
          <div class='cat-score {_score_class(s)}'>{s if s is not None else '—'}<span class='muted' style='font-size:0.9rem'> /100</span></div>
          <div class='cat-checkers'>{html.escape(checkers)}</div>
        </div>""")

    return f"""<!DOCTYPE html>
<html lang='en'><head><meta charset='utf-8'>
<title>SEO Page Score — {html.escape(target)}</title>
<style>{_CSS}</style></head><body>
<header>
  <h1>Page Score Report</h1>
  <p class='url'>{html.escape(target)}</p>
  <p class='muted'>Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · amazing-seo-skill</p>
</header>

<div class='score-card'>
  <div class='score-gauge {score_cls}'>{_emoji(score)} {score}</div>
  <div class='score-detail'>
    <p style='font-size:1.1rem;'>out of <strong>100</strong></p>
    <p class='muted'>Based on {summary.get('active_weight_pct', 0)}% of total weight</p>
    <p class='muted'>{len(findings)} findings total
      ({len(findings_by_sev.get('P0',[]))} critical, {len(findings_by_sev.get('P1',[]))} high, {len(findings_by_sev.get('P2',[]))} medium)</p>
  </div>
</div>

<h2>Score by category</h2>
<div class='cat-grid'>{"".join(cat_cards)}</div>

<h2>Findings</h2>
{"".join(sev_html) or "<p class='muted'>No findings — page is clean.</p>"}

<footer>Generated by <a href='https://github.com/metawhisp/amazing-seo-skill' style='color: var(--accent)'>amazing-seo-skill</a>. Re-run with <code>scripts/page_score.py</code>.</footer>
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

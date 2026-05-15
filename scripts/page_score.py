#!/usr/bin/env python3
"""
Single-page SEO orchestrator.

Runs every applicable L1 deterministic checker on one URL in parallel,
aggregates findings, computes a weighted Health Score (0-100), and emits
a structured report (JSON or Markdown).

Weights (sum = 100), aligned with skills/audit.md scoring rubric:

  technical (redirects + security)       25 %
  schema markup                          15 %
  images / CLS / LCP                     15 %
  links (internal + broken)              15 %
  CWV (PSI)                              15 %  (skipped if no API key — weight redistributed)
  GEO signals (llms.txt, hreflang)       10 %
  on-page extras (parse_html)            5  %

If a checker fails to run (e.g. no PSI key, no Gemini key), its weight is
**not** counted as 0 — it's removed from the denominator. Score reflects
only what was actually measured. The report makes this explicit.

Severity-based aggregation: each finding contributes -10 (P0), -5 (P1),
-2 (P2) from its category sub-score, floor 0.

Usage:
  page_score.py <url> [--format json|markdown] [--no-psi] [--max-links N]

Examples:
  page_score.py https://example.com
  page_score.py https://example.com --format markdown > REPORT.md
  page_score.py https://example.com --format json --no-psi
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

SCRIPTS_DIR = Path(__file__).parent
PY = sys.executable  # whoever launched us — likely .venv/bin/python


# Each checker: (key, script_filename, category, weight, default_args)
# Weights sum to 100. Content + CMS added in v0.4; on_page (parse_html) is now
# weight 0 (used as informational input only, not scored).
CHECKERS = [
    ("redirects",  "redirect_chain_checker.py",  "technical", 10,  []),
    ("security",   "security_headers_checker.py","technical", 10,  []),
    ("schema",     "schema_recommended_fields.py","schema",   15,  []),
    ("images",     "images_audit.py",            "images",    15,  ["--no-size-probe"]),
    ("links",      "broken_links_checker.py",    "links",     15,  ["--max-links", "60"]),
    ("psi",        "psi_checker.py",             "cwv",       15,  []),
    ("content",    "content_quality.py",         "content",   10,  []),
    ("hreflang",   "hreflang_checker.py",        "geo",        5,  []),
    ("llms",       "llms_txt_checker.py",        "geo",        5,  ["--skip-links"]),
    ("cms",        "cms_detector.py",            "platform",   0,  []),  # informational
    ("html",       "parse_html.py",              "on_page",    0,  ["--json"]),  # informational
]


def _run(checker_key: str, script: str, args: list[str], target: str) -> dict:
    """Run one checker. Returns dict with stdout (parsed), exit code, etc."""
    script_path = SCRIPTS_DIR / script
    if not script_path.exists():
        return {"key": checker_key, "error": f"missing: {script_path}", "skipped": True}

    # parse_html expects file or URL via --url; we save HTML first via fetch_page
    cmd = [PY, str(script_path)]
    if script == "parse_html.py":
        # Use fetch_page to get HTML to stdin
        try:
            fetch_proc = subprocess.run(
                [PY, str(SCRIPTS_DIR / "fetch_page.py"), target],
                capture_output=True, text=True, timeout=30,
            )
            if fetch_proc.returncode != 0:
                return {"key": checker_key, "error": "fetch_page failed", "skipped": True}
            html_input = fetch_proc.stdout
            proc = subprocess.run(
                cmd + ["--url", target, "--json"],
                input=html_input, capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {"key": checker_key, "error": "timeout", "skipped": True}
    else:
        try:
            proc = subprocess.run(
                cmd + [target] + args, capture_output=True, text=True, timeout=90,
            )
        except subprocess.TimeoutExpired:
            return {"key": checker_key, "error": "timeout", "skipped": True}

    # Parse JSON output if possible
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
    except json.JSONDecodeError:
        data = None

    return {
        "key": checker_key,
        "exit_code": proc.returncode,
        "data": data,
        "stderr_tail": proc.stderr[-200:] if proc.stderr else None,
    }


import re as _re

# Severity patterns — anchored to start of line OR specific full phrases to
# avoid substring false-positives like "non-https" matching "non-HTTPS subdomains".
_P0_PATTERNS = [
    _re.compile(r"^\d+ broken 4xx links", _re.I),
    _re.compile(r"missing required fields", _re.I),
    _re.compile(r"no clickjacking protection", _re.I),
    _re.compile(r"redirect loop detected", _re.I),
    _re.compile(r"served over HTTP, not HTTPS", _re.I),
    _re.compile(r"^missing self-reference", _re.I),
    _re.compile(r"chain longer than \d+ hops", _re.I),
    _re.compile(r"^\d+ 5xx-error links", _re.I),
    _re.compile(r"\bxss protection\b", _re.I),  # CSP unsafe-inline defeats XSS — P0
]
_P1_PATTERNS = [
    _re.compile(r"^missing (?!self-reference)", _re.I),
    _re.compile(r"^\d+ unreachable", _re.I),
    _re.compile(r"^\d+ 410-Gone", _re.I),
    _re.compile(r"all lastmod values identical", _re.I),
    _re.compile(r"302 \(temporary\) used for", _re.I),
    _re.compile(r"^\d+ images? without width", _re.I),
    _re.compile(r"^\d+/\d+ <img>.*missing alt", _re.I),
    _re.compile(r"^\d+ images? >= 500KB", _re.I),
    _re.compile(r"^\d+ large PNGs", _re.I),
    _re.compile(r"unsafe-eval", _re.I),
    _re.compile(r"hsts max-age too short", _re.I),
    _re.compile(r"hsts missing includesubdomains", _re.I),
    _re.compile(r"mixed content: \d+", _re.I),
    _re.compile(r"^\d+/\d+ below-fold images missing", _re.I),
]


def _classify_severity(text: str) -> str:
    for pat in _P0_PATTERNS:
        if pat.search(text):
            return "P0"
    for pat in _P1_PATTERNS:
        if pat.search(text):
            return "P1"
    return "P2"


def _score_for(result: dict) -> tuple[int, list[dict]]:
    """Return (sub_score 0-100, findings list) for one checker run."""
    data = result.get("data") or {}
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)]

    findings: list[dict] = []
    deduction = 0
    for issue in issues:
        text = issue if isinstance(issue, str) else str(issue)
        sev = _classify_severity(text)
        deduction += {"P0": 10, "P1": 5, "P2": 2}[sev]
        findings.append({"severity": sev, "text": text})

    sub_score = max(0, 100 - deduction)
    return sub_score, findings


def _has_psi_key() -> bool:
    """Quick check: is a PSI key available so we should bother running psi_checker?"""
    import os
    if os.environ.get("GOOGLE_PSI_API_KEY"):
        return True
    if shutil.which("security"):
        try:
            out = subprocess.run(
                ["security", "find-generic-password", "-s", "google-psi-api-key", "-w"],
                capture_output=True, timeout=3,
            )
            return out.returncode == 0
        except Exception:
            return False
    return False


def aggregate(results: list[dict]) -> dict:
    """Aggregate per-checker results into Health Score + category breakdown."""
    by_cat: dict[str, dict] = {}
    all_findings: list[dict] = []

    for r in results:
        ck_key = r["key"]
        # Look up weight + category
        meta = next((c for c in CHECKERS if c[0] == ck_key), None)
        if not meta:
            continue
        _, _, category, weight, _ = meta
        sub_score, findings = _score_for(r)
        for f in findings:
            f["checker"] = ck_key
            all_findings.append(f)

        by_cat.setdefault(category, {"weight_sum": 0, "score_sum": 0, "checkers": []})
        if r.get("skipped"):
            by_cat[category]["checkers"].append({"key": ck_key, "skipped": True,
                                                  "reason": r.get("error")})
            continue
        by_cat[category]["weight_sum"] += weight
        by_cat[category]["score_sum"]  += sub_score * weight
        by_cat[category]["checkers"].append({"key": ck_key, "sub_score": sub_score,
                                              "findings": len(findings),
                                              "exit_code": r.get("exit_code")})

    # Compute per-category weighted score
    total_weight = 0; total_score = 0
    for cat, agg in by_cat.items():
        if agg["weight_sum"] > 0:
            agg["score"] = round(agg["score_sum"] / agg["weight_sum"])
            total_weight += agg["weight_sum"]
            total_score  += agg["score_sum"]
        else:
            agg["score"] = None
        del agg["score_sum"]

    health_score = round(total_score / total_weight) if total_weight else 0
    return {
        "health_score": health_score,
        "active_weight_pct": total_weight,
        "by_category": by_cat,
        "all_findings": all_findings,
    }


def render_markdown(target: str, summary: dict, results: list[dict]) -> str:
    score = summary["health_score"]
    emoji = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
    lines = [
        f"# Page Score Report — {target}",
        "",
        f"**Health Score: {emoji} {score}/100**  ",
        f"_Based on {summary['active_weight_pct']}% of total weight_ "
        f"_(remaining {100 - summary['active_weight_pct']}% skipped — see Skipped section)_",
        "",
        "## Score by category",
        "",
        "| Category | Score | Checkers |",
        "|----------|-------|----------|",
    ]
    for cat, agg in sorted(summary["by_category"].items()):
        checkers = agg["checkers"]
        ran_checkers = [c for c in checkers if not c.get("skipped")]
        if agg["score"] is None:
            if ran_checkers:
                # Weight-0 informational checkers (CMS, parse_html)
                cks = ", ".join(c["key"] for c in ran_checkers)
                lines.append(f"| {cat} | informational | {cks} |")
            else:
                lines.append(f"| {cat} | — (skipped) | {len(checkers)} |")
        else:
            cks = ", ".join(
                f"{c['key']} {c['sub_score']}" for c in ran_checkers
            )
            lines.append(f"| {cat} | {agg['score']}/100 | {cks} |")

    # Findings by severity
    by_sev: dict[str, list[dict]] = {"P0": [], "P1": [], "P2": []}
    for f in summary["all_findings"]:
        by_sev.setdefault(f["severity"], []).append(f)

    lines.extend(["", "## Findings"])
    for sev_label, sev_emoji, sev_desc in [
        ("P0", "🛑", "Critical (blocks indexing or causes penalties)"),
        ("P1", "⚠️", "High (significantly impacts rankings)"),
        ("P2", "ℹ️", "Medium (optimization opportunity)"),
    ]:
        items = by_sev.get(sev_label, [])
        if not items:
            continue
        lines.extend(["", f"### {sev_emoji} {sev_label} — {sev_desc} ({len(items)})"])
        for f in items:
            lines.append(f"- **[{f['checker']}]** {f['text']}")

    # Skipped checkers
    skipped = [c for cat in summary["by_category"].values()
                 for c in cat["checkers"] if c.get("skipped")]
    if skipped:
        lines.extend(["", "## Skipped"])
        for s in skipped:
            lines.append(f"- `{s['key']}` — {s.get('reason', 'no reason given')}")

    lines.extend(["", "---",
                  "_Generated by amazing-seo-skill `page_score.py`. "
                  "Re-run any time. JSON output: `--format json`._"])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--format", choices=["json", "markdown"], default="markdown")
    ap.add_argument("--no-psi", action="store_true",
                    help="skip CWV via PageSpeed Insights even if a key is set")
    ap.add_argument("--max-links", type=int, default=60)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    # Filter checker list based on flags + key availability
    plan: list[tuple] = []
    psi_skip_reason = None
    for key, script, cat, weight, extra in CHECKERS:
        if key == "psi":
            if args.no_psi:
                psi_skip_reason = "user passed --no-psi"; continue
            if not _has_psi_key():
                psi_skip_reason = "no GOOGLE_PSI_API_KEY / Keychain entry"; continue
        if key == "links":
            extra = ["--max-links", str(args.max_links)]
        plan.append((key, script, extra))

    # Run in parallel
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {
            pool.submit(_run, k, s, e, args.url): k for k, s, e in plan
        }
        for fut in as_completed(future_map):
            results.append(fut.result())

    # Inject PSI-skipped placeholder so it shows in report
    if psi_skip_reason:
        results.append({"key": "psi", "skipped": True, "error": psi_skip_reason})

    # Stable order
    order = {c[0]: i for i, c in enumerate(CHECKERS)}
    results.sort(key=lambda r: order.get(r["key"], 99))

    summary = aggregate(results)

    if args.format == "json":
        print(json.dumps({"target": args.url, "summary": summary,
                          "results": results}, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(args.url, summary, results))

    return 0 if summary["health_score"] >= 70 else 2


if __name__ == "__main__":
    sys.exit(main())

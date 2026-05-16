#!/usr/bin/env python3
"""
PageSpeed Insights / Core Web Vitals deterministic checker.

Wraps the public PageSpeed Insights API v5. Returns:

  - CrUX field data (real-user 75th-percentile LCP / INP / CLS / FCP / TTFB)
    when available — flag missing as "page has insufficient field data"
  - Lighthouse lab data (simulated CWV for the same metrics) — always present
    if the page is reachable
  - per-metric verdict against current CWV thresholds (good / needs improvement
    / poor) for both field and lab
  - strategy = mobile by default (matches Google's mobile-first indexing);
    pass --desktop for desktop scoring

API key (optional, but improves rate limit from ~25 req/day to ~25,000):
  - reads `GOOGLE_PSI_API_KEY` env var first
  - falls back to macOS Keychain entry `google-psi-api-key`
  - works keyless for low-volume use

Exit code:
  0 = page reachable, all CWV pass thresholds (or no field data available)
  1 = API / network failure
  2 = at least one CWV metric fails Good threshold

Usage:
  psi_checker.py <url> [--desktop] [--strategy mobile|desktop]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import requests


_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# Current Core Web Vitals thresholds (kept in sync with references/cwv-thresholds.md)
_THRESHOLDS = {
    "LCP_MS":  (2500, 4000),      # good <=2500ms, needs <=4000ms, poor >4000ms
    "INP_MS":  (200, 500),
    "CLS":     (0.10, 0.25),
    "FCP_MS":  (1800, 3000),
    "TTFB_MS": (800, 1800),
}


def _resolve_api_key() -> str | None:
    """Env var first, then macOS Keychain. Returns None if neither is set."""
    if k := os.environ.get("GOOGLE_PSI_API_KEY"):
        return k.strip()
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "google-psi-api-key", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _verdict(value: float | None, thresholds: tuple[float, float]) -> str:
    if value is None:
        return "unknown"
    good, ni = thresholds
    if value <= good:
        return "good"
    if value <= ni:
        return "needs_improvement"
    return "poor"


def _extract_crux(payload: dict) -> dict:
    """Pull CrUX field data (real users) at the URL level."""
    loading = payload.get("loadingExperience") or {}
    metrics = loading.get("metrics") or {}
    out: dict = {
        "has_field_data": bool(metrics),
        "overall_category": loading.get("overall_category"),
    }
    mapping = [
        ("LARGEST_CONTENTFUL_PAINT_MS", "lcp_ms", "LCP_MS"),
        ("INTERACTION_TO_NEXT_PAINT", "inp_ms", "INP_MS"),
        ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "cls", "CLS"),
        ("FIRST_CONTENTFUL_PAINT_MS", "fcp_ms", "FCP_MS"),
        ("EXPERIMENTAL_TIME_TO_FIRST_BYTE", "ttfb_ms", "TTFB_MS"),
    ]
    for crux_key, out_key, thresh_key in mapping:
        m = metrics.get(crux_key) or {}
        p75 = m.get("percentile")
        # CLS in CrUX is delivered ×100 in `percentile` historically; check field
        if crux_key == "CUMULATIVE_LAYOUT_SHIFT_SCORE" and p75 is not None:
            p75 = p75 / 100.0
        out[out_key] = p75
        out[f"{out_key}_verdict"] = _verdict(p75, _THRESHOLDS[thresh_key])
    return out


def _extract_lab(payload: dict) -> dict:
    """Pull Lighthouse lab data (simulated)."""
    audits = (
        payload.get("lighthouseResult", {}).get("audits") or {}
    )
    def _num(k: str) -> float | None:
        return (audits.get(k) or {}).get("numericValue")

    lcp = _num("largest-contentful-paint")
    cls = _num("cumulative-layout-shift")
    fcp = _num("first-contentful-paint")
    tbt = _num("total-blocking-time")  # lab proxy for interactivity (no field INP in lab)
    ttfb = _num("server-response-time")

    score = (
        payload.get("lighthouseResult", {})
        .get("categories", {})
        .get("performance", {})
        .get("score")
    )

    return {
        "performance_score": round(score * 100) if isinstance(score, (int, float)) else None,
        "lcp_ms": lcp,
        "lcp_verdict": _verdict(lcp, _THRESHOLDS["LCP_MS"]),
        "cls": cls,
        "cls_verdict": _verdict(cls, _THRESHOLDS["CLS"]),
        "fcp_ms": fcp,
        "fcp_verdict": _verdict(fcp, _THRESHOLDS["FCP_MS"]),
        "tbt_ms": tbt,  # lab Total Blocking Time — not a CWV but informative
        "ttfb_ms": ttfb,
        "ttfb_verdict": _verdict(ttfb, _THRESHOLDS["TTFB_MS"]),
    }


def run_psi(url: str, strategy: str, api_key: str | None) -> dict:
    # Direct requests.get (not _fetch.fetch) — exempt because we hit a
    # fixed Google API endpoint, not arbitrary user URLs. SSRF guard
    # would block 142.250.x.x ranges spuriously. Retry on 5xx manually.
    params = {"url": url, "strategy": strategy.upper()}
    if api_key:
        params["key"] = api_key
    for attempt in range(3):
        r = requests.get(_API_URL, params=params, timeout=60)
        if r.status_code >= 500 and attempt < 2:
            import time
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--strategy", default="mobile", choices=["mobile", "desktop"])
    ap.add_argument("--desktop", action="store_true", help="shortcut for --strategy desktop")
    args = ap.parse_args()

    strategy = "desktop" if args.desktop else args.strategy

    api_key = _resolve_api_key()
    out: dict = {
        "url": args.url,
        "strategy": strategy,
        "api_key_used": bool(api_key),
    }

    try:
        payload = run_psi(args.url, strategy, api_key)
    except requests.HTTPError as e:
        out["error"] = f"PSI API HTTP {e.response.status_code}: {e.response.text[:300]}"
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1
    except requests.RequestException as e:
        out["error"] = str(e)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1

    out["field_data"] = _extract_crux(payload)
    out["lab_data"] = _extract_lab(payload)
    out["analyzed_url"] = payload.get("id")

    # Decide pass/fail using FIELD data when available (Google ranks on field),
    # falling back to LAB only when field is missing.
    cwv_metrics = ("lcp", "inp", "cls")
    field_verdicts = []
    lab_verdicts = []
    for m in cwv_metrics:
        suffix = "_ms" if m in ("lcp", "inp") else ""
        fv = out["field_data"].get(f"{m}{suffix}_verdict")
        lv = out["lab_data"].get(f"{m}{suffix}_verdict") if m != "inp" else None
        field_verdicts.append(fv)
        if lv:
            lab_verdicts.append(lv)

    source = "field" if out["field_data"].get("has_field_data") else "lab"
    out["source_for_verdict"] = source
    verdicts = field_verdicts if source == "field" else lab_verdicts
    any_poor = any(v == "poor" for v in verdicts if v)
    any_ni = any(v == "needs_improvement" for v in verdicts if v)

    issues = []
    for m, v in zip(cwv_metrics, verdicts):
        if v == "poor":
            issues.append(f"{m.upper()} = poor ({source})")
        elif v == "needs_improvement":
            issues.append(f"{m.upper()} = needs improvement ({source})")
    out["issues"] = issues

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if (any_poor or any_ni) else 0


if __name__ == "__main__":
    sys.exit(main())

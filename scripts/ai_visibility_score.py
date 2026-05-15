#!/usr/bin/env python3
"""
AI Visibility Score — composite metric for how discoverable a domain is
to AI search systems (ChatGPT, Claude, Perplexity, Grok, Gemini, AI Overviews).

Rationale (verified May 2026 — Position.digital, Ahrefs, 5W Research):
  - AI Overviews now reach 2B users/month; top-10 share of citations
    dropped from 92% to 38%, meaning off-page brand signals + technical
    readiness now matter more than rank alone.
  - AI crawlers don't execute JavaScript — server-side rendering is the
    gate. Sites with 50%+ content client-side get little to no AI
    visibility from non-Googlebot crawlers.
  - llms.txt is rapidly emerging as the canonical "instructions for AI"
    file — its presence + quality signals readiness.
  - Schema markup helps AI parse and attribute content; missing/incorrect
    schema is a major attribution gap.

Components (weighted, sum=100):

  | Component                       | Weight | What it checks                          |
  |---------------------------------|--------|-----------------------------------------|
  | AI crawler accessibility        |  25%   | robots.txt allows GPTBot, ClaudeBot, etc. |
  | Server-side rendering           |  25%   | js_rendering_diff: raw word_count / rendered |
  | Schema completeness             |  15%   | schema_recommended_fields aggregated     |
  | llms.txt quality                |  15%   | llms_txt_checker score                  |
  | Hreflang clarity                |  10%   | declared languages help AI route correctly |
  | Live citation rate              |  10%   | aeo_gemini citation_rate (if key avail)  |

Components without measurement (e.g. no Gemini key) are excluded from the
denominator — score reflects only what was measured. The verdict makes
this explicit.

Exit code:
  0 = score >= 70 (good AI visibility)
  1 = fetch failed
  2 = score < 70

Usage:
  ai_visibility_score.py <url>
  ai_visibility_score.py <url> --no-js-render    # skip Playwright (faster)
  ai_visibility_score.py <url> --queries "best email tool" "alternatives to X"
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent
PY = sys.executable


def _run_json(script: str, args: list[str], timeout: int = 120) -> dict | None:
    try:
        r = subprocess.run(
            [PY, str(SCRIPTS / script)] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        if r.stdout.strip().startswith("{"):
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def _component_robots(url: str) -> tuple[float | None, dict]:
    """Robots: % of 20 AI crawlers NOT blocked."""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc or url
    data = _run_json("robots_checker.py", [domain], timeout=20)
    if not data or "bot_access" not in data:
        return None, {"reason": "robots_checker failed or robots.txt missing"}
    bots = data["bot_access"]
    if not bots:
        return None, {"reason": "no bot access info"}
    allowed = sum(1 for b in bots if not b["root_blocked"])
    score = round(100 * allowed / len(bots))
    return score, {
        "bots_total": len(bots),
        "bots_allowed": allowed,
        "bots_blocked": [b["bot"] for b in bots if b["root_blocked"]],
    }


def _component_ssr(url: str) -> tuple[float | None, dict]:
    """SSR completeness: raw word_count / rendered word_count, capped 100."""
    data = _run_json("js_rendering_diff.py", [url], timeout=90)
    if not data or "raw_seo" not in data:
        return None, {"reason": data.get("error", "js_rendering_diff failed") if data else "no data"}
    raw_w = data["raw_seo"]["word_count"]
    rendered_w = data["rendered_seo"]["word_count"]
    if rendered_w == 0:
        return 0.0, {"reason": "rendered page has no visible words"}
    ratio = min(1.0, raw_w / rendered_w)
    score = round(ratio * 100)
    return score, {
        "raw_word_count": raw_w,
        "rendered_word_count": rendered_w,
        "ssr_ratio_pct": round(ratio * 100, 1),
        "p0_findings": [f for f in data.get("findings", []) if f["severity"] == "P0"],
    }


def _component_schema(url: str) -> tuple[float | None, dict]:
    """Schema: average completeness across all items, weighted by required-spec coverage."""
    data = _run_json("schema_recommended_fields.py", [url], timeout=30)
    if not data:
        return None, {"reason": "schema_recommended_fields failed"}
    items = data.get("items", [])
    if not items:
        return 30.0, {"reason": "no JSON-LD on page", "score_floor": 30}
    completeness_vals = [i.get("completeness_score") for i in items
                         if i.get("completeness_score") is not None]
    if not completeness_vals:
        return 50.0, {"reason": "items present but no completeness data"}
    avg = sum(completeness_vals) / len(completeness_vals)
    missing_required = data.get("items_missing_any_required", 0)
    # Penalty: each item missing required fields = -10 points (capped)
    penalty = min(40, missing_required * 10)
    score = max(0, round(avg - penalty))
    return score, {
        "items_total": len(items),
        "average_completeness": round(avg, 1),
        "items_missing_required": missing_required,
        "schema_types": sorted(set(i.get("type", "?") for i in items)),
    }


def _component_llms_txt(url: str) -> tuple[float | None, dict]:
    """llms.txt: direct score from checker (or 0 if missing)."""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc or url
    data = _run_json("llms_txt_checker.py", [domain, "--skip-links"], timeout=20)
    if not data:
        return None, {"reason": "llms_txt_checker failed"}
    if not data.get("exists"):
        return 0.0, {"reason": "no /llms.txt at site root",
                     "recommendation": "create /llms.txt — emerging AEO standard"}
    return float(data.get("score", 0)), {
        "exists": True,
        "checker_score": data.get("score"),
        "issues": data.get("issues", []),
    }


def _component_hreflang(url: str) -> tuple[float | None, dict]:
    """Hreflang: declared = +; valid x-default + self-ref = max."""
    data = _run_json("hreflang_checker.py", [url], timeout=30)
    if not data:
        return None, {"reason": "hreflang_checker failed"}
    declarations = data.get("declarations_count", 0)
    if declarations == 0:
        return 50.0, {"reason": "no hreflang declarations (single-language site or missing)",
                      "note": "single-language sites can ignore this component"}
    issues = data.get("issues", [])
    # Start at 100, subtract for issues
    score = 100 - len(issues) * 20
    return max(0, score), {
        "declarations_count": declarations,
        "languages": data.get("languages", []),
        "issues": issues,
    }


def _component_citations(url: str, queries: list[str]) -> tuple[float | None, dict]:
    """Live Gemini citation probe — share of queries citing the domain."""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc or url
    # Skip if no key available
    if not (os.environ.get("GOOGLE_GEMINI_API_KEY") or _has_keychain_key("google-gemini-api-key")):
        return None, {"reason": "no google-gemini-api-key — skipping live citation probe"}
    if not queries:
        return None, {"reason": "no --queries provided"}
    data = _run_json("aeo_gemini.py", [domain] + queries + ["--json"], timeout=180)
    if not data or "citation_rate" not in data:
        return None, {"reason": "aeo_gemini failed or no key"}
    rate = data["citation_rate"]
    score = round(rate * 100)
    return score, {
        "queries": data.get("queries_total"),
        "cited": data.get("queries_cited"),
        "rate_pct": round(rate * 100, 1),
    }


def _has_keychain_key(name: str) -> bool:
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", name, "-w"],
                           capture_output=True, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


# (key, label, weight%, runner)
COMPONENTS = [
    ("robots",    "AI crawler accessibility",   25, _component_robots),
    ("ssr",       "Server-side rendering",      25, _component_ssr),
    ("schema",    "Schema completeness",        15, _component_schema),
    ("llms_txt",  "llms.txt quality",           15, _component_llms_txt),
    ("hreflang",  "Hreflang clarity",           10, _component_hreflang),
    ("citations", "Live Gemini citation rate",  10, None),  # special — uses queries
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--queries", nargs="*", default=[],
                    help="queries for live Gemini citation probe (requires google-gemini-api-key)")
    ap.add_argument("--no-js-render", action="store_true",
                    help="skip Playwright SSR check (faster but loses 25%% weight)")
    args = ap.parse_args()

    url = args.url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    components_out: list[dict] = []
    total_weight = 0
    total_score = 0

    for key, label, weight, runner in COMPONENTS:
        if key == "ssr" and args.no_js_render:
            components_out.append({"key": key, "label": label, "weight": weight,
                                    "score": None, "skipped": True,
                                    "reason": "--no-js-render"})
            continue
        if key == "citations":
            score, detail = _component_citations(url, args.queries)
        else:
            score, detail = runner(url)
        if score is None:
            components_out.append({"key": key, "label": label, "weight": weight,
                                    "score": None, "skipped": True, **detail})
            continue
        components_out.append({"key": key, "label": label, "weight": weight,
                                "score": score, **detail})
        total_weight += weight
        total_score += score * weight

    if total_weight == 0:
        print(json.dumps({"error": "all components skipped", "components": components_out}, indent=2))
        return 1

    final = round(total_score / total_weight)

    # Verdict
    if final >= 80:
        verdict = "excellent — site is well-positioned for AI search visibility"
    elif final >= 60:
        verdict = "good — solid foundation, address P1 components to push above 80"
    elif final >= 40:
        verdict = "weak — multiple critical gaps; AI surfaces likely under-citing this domain"
    else:
        verdict = "poor — major work needed; AI crawlers/citations likely failing entirely"

    out = {
        "url": url,
        "ai_visibility_score": final,
        "active_weight_pct": total_weight,
        "verdict": verdict,
        "components": components_out,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if final >= 70 else 2


if __name__ == "__main__":
    sys.exit(main())

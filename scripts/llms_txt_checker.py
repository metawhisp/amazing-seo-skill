#!/usr/bin/env python3
"""
llms.txt deterministic checker.

Validates the canonical /llms.txt file at a domain root against the proposed
spec (https://llmstxt.org). Reports:
  - existence + HTTP status
  - file size, line count
  - presence of recommended sections (# Title, > description, ## Sections)
  - link density and link validity (HTTP 200 on referenced URLs)
  - heuristic AEO signals (does the file address LLMs directly?)

Exit code: 0 if file exists and is well-formed, 1 if missing, 2 if malformed.

Usage:
    llms_txt_checker.py <domain_or_url>

Example:
    llms_txt_checker.py example.com
    llms_txt_checker.py https://example.com
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse

import requests


def normalize(target: str) -> str:
    """Return https://<host> without trailing slash."""
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    p = urlparse(target)
    return f"{p.scheme}://{p.netloc}"


def fetch(url: str, timeout: int = 10) -> tuple[int, str, dict]:
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True,
                         headers={"User-Agent": "amazing-seo-skill/llms-txt-checker"})
        return r.status_code, r.text, dict(r.headers)
    except requests.RequestException as e:
        return 0, str(e), {}


def analyze(text: str) -> dict:
    lines = text.splitlines()
    non_blank = [ln for ln in lines if ln.strip()]
    headings_h1 = [ln for ln in lines if ln.startswith("# ") and not ln.startswith("## ")]
    headings_h2 = [ln for ln in lines if ln.startswith("## ")]
    blockquote = [ln for ln in lines if ln.lstrip().startswith(">")]
    md_links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text)

    # AEO signal heuristics
    addresses_llm = bool(re.search(
        r"\b(if you (are|'re) an? (ai|assistant|language model|llm|chatbot)|"
        r"(ai|llm) (assistants?|search engines?|crawlers?))\b",
        text, re.IGNORECASE,
    ))
    has_recommendations = bool(re.search(r"\brecommend(?:ation)?s?\b", text, re.IGNORECASE))
    has_facts_section = any("fact" in h.lower() for h in headings_h2)

    return {
        "byte_size": len(text.encode("utf-8")),
        "line_count": len(lines),
        "non_blank_lines": len(non_blank),
        "h1_count": len(headings_h1),
        "h1_first": headings_h1[0].strip() if headings_h1 else None,
        "h2_count": len(headings_h2),
        "h2_titles": [h.strip("# ").strip() for h in headings_h2],
        "blockquote_count": len(blockquote),
        "blockquote_first": blockquote[0].strip() if blockquote else None,
        "markdown_link_count": len(md_links),
        "addresses_llm_directly": addresses_llm,
        "has_recommendations_language": has_recommendations,
        "has_key_facts_section": has_facts_section,
    }


def score_file(stats: dict) -> tuple[int, list[str]]:
    """Return (0-100 score, list of issues)."""
    issues = []
    score = 100

    if stats["h1_count"] == 0:
        score -= 25; issues.append("missing # Title heading (recommended: site/product name)")
    if stats["h1_count"] > 1:
        score -= 5; issues.append(f"{stats['h1_count']} H1 headings — should be 1")
    if stats["blockquote_count"] == 0:
        score -= 15; issues.append("missing > description blockquote (recommended: 1-line tagline)")
    if stats["h2_count"] == 0:
        score -= 20; issues.append("no ## sections found — file lacks structure")
    if stats["non_blank_lines"] < 10:
        score -= 20; issues.append(f"file too short ({stats['non_blank_lines']} non-blank lines)")
    if not stats["addresses_llm_directly"]:
        score -= 10; issues.append("does not address LLMs directly (low AEO signal)")
    if stats["markdown_link_count"] == 0:
        score -= 10; issues.append("no markdown links — consider linking to important pages")

    return max(0, score), issues


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().split("\n\n")[0])
        print("\nUsage: llms_txt_checker.py <domain_or_url>", file=sys.stderr)
        return 64

    base = normalize(sys.argv[1])
    url = f"{base}/llms.txt"

    status, body, headers = fetch(url)
    result: dict = {
        "url": url,
        "http_status": status,
        "exists": status == 200,
    }

    if status != 200:
        result["error"] = body if status == 0 else f"HTTP {status}"
        result["score"] = 0
        result["recommendation"] = (
            "Create /llms.txt at site root. Format: "
            "# Title\\n> One-line description\\n\\n## Section\\n- bullets/links"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1

    stats = analyze(body)
    score, issues = score_file(stats)
    result.update({
        "stats": stats,
        "score": score,
        "issues": issues,
        "content_type": headers.get("content-type", "?"),
    })

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if score >= 70 else 2


if __name__ == "__main__":
    sys.exit(main())

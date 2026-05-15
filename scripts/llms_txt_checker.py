#!/usr/bin/env python3
"""
llms.txt deterministic checker.

Validates the canonical /llms.txt file at a domain root against the proposed
spec (https://llmstxt.org). Reports:
  - existence + HTTP status
  - file size, line count
  - presence of recommended sections (# Title, > description, ## Sections)
  - link density + link validity: each markdown link is HEAD-checked (GET
    fallback if HEAD is rejected). Capped at 30 unique URLs.
  - heuristic AEO signals (does the file address LLMs directly?)

Exit code: 0 if file exists, is well-formed, and links resolve;
           1 if missing; 2 if malformed or links broken.

Usage:
    llms_txt_checker.py <domain_or_url> [--skip-links]

Example:
    llms_txt_checker.py example.com
    llms_txt_checker.py https://example.com
    llms_txt_checker.py example.com --skip-links  # don't probe link targets
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests

from _fetch import fetch as _fetch_url


def normalize(target: str) -> str:
    """Return https://<host> without trailing slash."""
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    p = urlparse(target)
    return f"{p.scheme}://{p.netloc}"


def fetch(url: str, timeout: int = 10) -> tuple[int, str, dict]:
    try:
        r = _fetch_url(url, timeout=timeout)
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


def _check_links(text: str, base_url: str, max_links: int = 30) -> dict:
    """HEAD-check every markdown link in the file (capped at max_links).

    Reports broken (non-200) and unreachable URLs. HEAD with GET fallback so
    sites that 405 on HEAD are still validated.
    """
    md_links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text)
    seen: set[str] = set()
    targets: list[str] = []
    for _, href in md_links:
        absolute = urljoin(base_url, href.strip())
        if absolute in seen:
            continue
        seen.add(absolute)
        targets.append(absolute)
        if len(targets) >= max_links:
            break

    def _probe(url: str) -> tuple[str, int | None, str | None]:
        try:
            r = requests.head(url, timeout=10, allow_redirects=True,
                              headers={"User-Agent": "amazing-seo-skill/llms-txt-link-check"})
            if r.status_code in (405, 403) or r.status_code >= 400:
                r = _fetch_url(url, timeout=10)
            return url, r.status_code, None
        except requests.RequestException as e:
            return url, None, str(e)

    results: list[dict] = []
    if not targets:
        return {"links_total": 0, "links_checked": 0, "broken": [], "unreachable": []}

    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        for fut in as_completed(pool.submit(_probe, u) for u in targets):
            url, status, err = fut.result()
            results.append({"url": url, "status": status, "error": err})

    broken = [r for r in results if r["status"] is not None and r["status"] >= 400]
    unreachable = [r for r in results if r["status"] is None]
    return {
        "links_total": len(md_links),
        "links_checked": len(targets),
        "broken_count": len(broken),
        "unreachable_count": len(unreachable),
        "broken": broken,
        "unreachable": unreachable,
    }


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(__doc__.strip().split("\n\n")[0])
        print("\nUsage: llms_txt_checker.py <domain_or_url> [--skip-links]", file=sys.stderr)
        return 64
    skip_links = "--skip-links" in sys.argv

    base = normalize(sys.argv[1] if not sys.argv[1].startswith("--") else sys.argv[2])
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

    if not skip_links:
        link_check = _check_links(body, base)
        result["link_validity"] = link_check
        if link_check.get("broken_count", 0) > 0:
            issues.append(f"{link_check['broken_count']} of {link_check['links_checked']} linked URLs return 4xx/5xx")
            score = max(0, score - min(20, link_check["broken_count"] * 3))
            result["score"] = score
            result["issues"] = issues

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if score >= 70 else 2


if __name__ == "__main__":
    sys.exit(main())

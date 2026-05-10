#!/usr/bin/env python3
"""
Hreflang / international SEO deterministic checker.

For a given URL: fetch HTML and HTTP headers, extract all hreflang declarations
from <link rel="alternate"> tags AND from HTTP Link headers, then validate:

  - language code format (BCP-47)
  - x-default presence
  - return-link reciprocity (each declared alternate must, when fetched, point
    back to the current URL)
  - duplicate / conflicting declarations
  - self-reference (each page must include hreflang for itself)

Exit code: 0 if all valid, 2 if issues found, 1 if fetch failed.

Usage:
    hreflang_checker.py <url> [--check-reciprocity]
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BCP47 = re.compile(r"^(?:x-default|[a-z]{2,3}(?:-[A-Z]{2})?(?:-[a-z]{4})?(?:-[A-Z]{2})?)$", re.IGNORECASE)


def fetch(url: str, timeout: int = 15):
    return requests.get(
        url, timeout=timeout, allow_redirects=True,
        headers={"User-Agent": "amazing-seo-skill/hreflang-checker"},
    )


def extract_from_html(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for link in soup.find_all("link", rel="alternate"):
        lang = link.get("hreflang")
        href = link.get("href")
        if lang and href:
            out.append({"lang": lang, "href": urljoin(base_url, href), "source": "html"})
    return out


def extract_from_headers(headers: dict, base_url: str) -> list[dict]:
    link_hdr = headers.get("Link") or headers.get("link") or ""
    out = []
    # Parse Link header per RFC 5988
    for raw in re.split(r",\s*(?=<)", link_hdr):
        m = re.match(r"<([^>]+)>(.*)", raw.strip())
        if not m:
            continue
        href, params = m.group(1), m.group(2)
        if "rel=\"alternate\"" not in params:
            continue
        lang_m = re.search(r"hreflang=\"([^\"]+)\"", params)
        if lang_m:
            out.append({"lang": lang_m.group(1), "href": urljoin(base_url, href), "source": "header"})
    return out


def validate(url: str, decls: list[dict], check_reciprocity: bool) -> dict:
    issues: list[str] = []
    self_url = url.rstrip("/")
    langs_seen: dict[str, list[str]] = {}

    for d in decls:
        # BCP-47 format
        if not BCP47.match(d["lang"]):
            issues.append(f"invalid hreflang code: {d['lang']!r} for {d['href']}")
        langs_seen.setdefault(d["lang"], []).append(d["href"])

    # Duplicate language → multiple URLs
    for lang, urls in langs_seen.items():
        unique = set(urls)
        if len(unique) > 1:
            issues.append(f"hreflang={lang!r} points to {len(unique)} different URLs: {sorted(unique)}")

    # x-default
    if "x-default" not in {d["lang"].lower() for d in decls}:
        issues.append("missing x-default — recommended for unmatched language/region requests")

    # Self-reference: current URL must appear among the declared hreflangs
    declared_hrefs = {d["href"].rstrip("/") for d in decls}
    if self_url not in declared_hrefs:
        issues.append(f"missing self-reference: current URL {self_url} not declared as any hreflang variant")

    reciprocity_problems = []
    if check_reciprocity and decls:
        for d in decls:
            if d["href"].rstrip("/") == self_url:
                continue
            try:
                r = fetch(d["href"], timeout=15)
                back = extract_from_html(r.text, d["href"]) + extract_from_headers(dict(r.headers), d["href"])
                back_hrefs = {b["href"].rstrip("/") for b in back}
                if self_url not in back_hrefs:
                    reciprocity_problems.append({"target": d["href"], "lang": d["lang"], "missing_return_link": True})
            except requests.RequestException as e:
                reciprocity_problems.append({"target": d["href"], "lang": d["lang"], "error": str(e)})

    return {"issues": issues, "reciprocity_problems": reciprocity_problems}


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: hreflang_checker.py <url> [--check-reciprocity]", file=sys.stderr)
        return 64
    url = args[0]
    check_reciprocity = "--check-reciprocity" in args[1:]

    try:
        r = fetch(url)
    except requests.RequestException as e:
        print(json.dumps({"url": url, "error": str(e)}, indent=2))
        return 1

    decls = extract_from_html(r.text, url) + extract_from_headers(dict(r.headers), url)
    validation = validate(url, decls, check_reciprocity)

    out = {
        "url": url,
        "http_status": r.status_code,
        "declarations_count": len(decls),
        "languages": sorted({d["lang"] for d in decls}),
        "declarations": decls,
        **validation,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if validation["issues"] or validation["reciprocity_problems"] else 0


if __name__ == "__main__":
    sys.exit(main())

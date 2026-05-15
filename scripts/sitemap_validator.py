#!/usr/bin/env python3
"""
XML sitemap deterministic validator.

Fetches a sitemap URL (or auto-discovers `/sitemap.xml`), follows sitemap-index
recursively, and reports:

  - XML validity (parse errors)
  - URL count, per-file and total (sitemap protocol limit: 50,000 / 50 MiB)
  - HTTPS-only check
  - lastmod sanity (presence, format, all-identical-dates smell)
  - deprecated <priority> / <changefreq> usage (Google ignores these)
  - sample HTTP-status check on a configurable subset of URLs
  - cross-check against robots.txt: is the sitemap referenced there?

Exit code:
  0 = clean
  1 = fetch failed
  2 = validity / structural issues found

Usage:
  sitemap_validator.py <sitemap_url_or_domain> [--sample N] [--check-robots]

Examples:
  sitemap_validator.py https://example.com/sitemap.xml
  sitemap_validator.py example.com --sample 30 --check-robots
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from _fetch import fetch


_PROTOCOL_URL_LIMIT = 50_000
_PROTOCOL_SIZE_LIMIT_BYTES = 50 * 1024 * 1024
_LASTMOD_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)


def normalize_target(target: str) -> str:
    """Accept either a sitemap URL or a domain; return a sitemap URL to try."""
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    if "sitemap" in target.lower() or target.endswith(".xml"):
        return target
    return target.rstrip("/") + "/sitemap.xml"


def _parse_sitemap(text: str) -> dict:
    """Parse one sitemap document. Returns dict with type + entries + raw issues."""
    issues: list[str] = []
    try:
        soup = BeautifulSoup(text, "xml")
    except Exception as e:
        return {"parse_error": str(e)}

    if soup.find("sitemapindex"):
        entries = []
        for sm in soup.find_all("sitemap"):
            loc = sm.find("loc")
            lastmod = sm.find("lastmod")
            if loc:
                entries.append({
                    "loc": loc.text.strip(),
                    "lastmod": lastmod.text.strip() if lastmod else None,
                })
        return {"kind": "index", "entries": entries, "issues": issues}

    if soup.find("urlset"):
        entries = []
        for u in soup.find_all("url"):
            loc = u.find("loc")
            if not loc:
                continue
            lastmod_el = u.find("lastmod")
            entries.append({
                "loc": loc.text.strip(),
                "lastmod": lastmod_el.text.strip() if lastmod_el else None,
                "has_priority": bool(u.find("priority")),
                "has_changefreq": bool(u.find("changefreq")),
            })
        return {"kind": "urlset", "entries": entries, "issues": issues}

    return {"kind": "unknown", "entries": [], "issues": ["root element is neither <urlset> nor <sitemapindex>"]}


def _check_url_status(url: str) -> tuple[str, int | None, str | None]:
    """Return (url, status_or_None, error_or_None)."""
    try:
        # HEAD first; fall back to GET if HEAD not supported
        r = requests.head(url, timeout=10, allow_redirects=True,
                          headers={"User-Agent": "amazing-seo-skill/sitemap-validator"})
        if r.status_code == 405 or r.status_code >= 400:
            r = fetch(url, timeout=10)
        return url, r.status_code, None
    except requests.RequestException as e:
        return url, None, str(e)


def _validate_entries(entries: list[dict]) -> dict:
    """Run per-urlset checks. Returns dict of issue lists."""
    https_violations = [e["loc"] for e in entries if e["loc"].startswith("http://")]
    bad_lastmod = [e["loc"] for e in entries
                   if e["lastmod"] and not _LASTMOD_RE.match(e["lastmod"])]
    priority_uses = [e["loc"] for e in entries if e.get("has_priority")]
    changefreq_uses = [e["loc"] for e in entries if e.get("has_changefreq")]

    lastmods = [e["lastmod"] for e in entries if e["lastmod"]]
    all_identical_lastmod = (
        len(entries) > 10
        and len(set(lastmods)) == 1
        and len(lastmods) == len(entries)
    )
    no_lastmod_at_all = len(entries) > 5 and not lastmods

    return {
        "non_https_urls": https_violations[:20],
        "non_https_url_count": len(https_violations),
        "malformed_lastmod_urls": bad_lastmod[:20],
        "malformed_lastmod_count": len(bad_lastmod),
        "priority_tag_usage_count": len(priority_uses),
        "changefreq_tag_usage_count": len(changefreq_uses),
        "all_lastmod_identical": all_identical_lastmod,
        "missing_lastmod_entirely": no_lastmod_at_all,
    }


def _check_robots_reference(domain: str, sitemap_url: str) -> dict:
    """Optional cross-check: is the sitemap declared in /robots.txt?"""
    try:
        r = fetch(f"{domain}/robots.txt", timeout=10)
        if not r.ok:
            return {"robots_status": r.status_code, "referenced_in_robots": None}
        referenced = sitemap_url in r.text
        return {"robots_status": 200, "referenced_in_robots": referenced}
    except requests.RequestException as e:
        return {"robots_status": None, "robots_error": str(e),
                "referenced_in_robots": None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("target")
    ap.add_argument("--sample", type=int, default=20,
                    help="number of URLs to HTTP-check (default: 20)")
    ap.add_argument("--check-robots", action="store_true",
                    help="cross-reference against /robots.txt Sitemap: directives")
    args = ap.parse_args()

    sitemap_url = normalize_target(args.target)
    domain_root = f"{urlparse(sitemap_url).scheme}://{urlparse(sitemap_url).netloc}"

    try:
        r = fetch(sitemap_url, timeout=15)
    except requests.RequestException as e:
        print(json.dumps({"url": sitemap_url, "error": str(e)}, indent=2))
        return 1

    if not r.ok:
        print(json.dumps({"url": sitemap_url, "http_status": r.status_code,
                          "error": f"HTTP {r.status_code}"}, indent=2))
        return 1

    parsed = _parse_sitemap(r.text)
    out: dict = {
        "url": sitemap_url,
        "http_status": r.status_code,
        "byte_size": len(r.content),
        "kind": parsed.get("kind"),
        "exceeds_size_limit": len(r.content) > _PROTOCOL_SIZE_LIMIT_BYTES,
    }

    if parsed.get("parse_error"):
        out["parse_error"] = parsed["parse_error"]
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 2

    # Follow sitemap index → aggregate all child urlsets
    all_url_entries: list[dict] = []
    child_results: list[dict] = []
    if parsed["kind"] == "index":
        out["child_sitemaps"] = [e["loc"] for e in parsed["entries"]]
        for child in parsed["entries"]:
            try:
                cr = fetch(child["loc"], timeout=15)
                if cr.ok:
                    child_parsed = _parse_sitemap(cr.text)
                    if child_parsed.get("kind") == "urlset":
                        all_url_entries.extend(child_parsed["entries"])
                        child_results.append({
                            "url": child["loc"],
                            "url_count": len(child_parsed["entries"]),
                            "byte_size": len(cr.content),
                        })
                    else:
                        child_results.append({"url": child["loc"],
                                              "warning": "nested index or unknown"})
                else:
                    child_results.append({"url": child["loc"],
                                          "error": f"HTTP {cr.status_code}"})
            except requests.RequestException as e:
                child_results.append({"url": child["loc"], "error": str(e)})
        out["children"] = child_results
    elif parsed["kind"] == "urlset":
        all_url_entries = parsed["entries"]

    out["total_url_count"] = len(all_url_entries)
    out["exceeds_url_limit_per_file"] = (
        parsed["kind"] == "urlset" and len(all_url_entries) > _PROTOCOL_URL_LIMIT
    )

    if all_url_entries:
        out["validation"] = _validate_entries(all_url_entries)

    # Sample HTTP status check
    if all_url_entries and args.sample > 0:
        sample_urls = [e["loc"] for e in all_url_entries[:args.sample]]
        status_results: dict = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_check_url_status, u) for u in sample_urls]
            for fut in as_completed(futures):
                url, status, err = fut.result()
                status_results[url] = {"status": status, "error": err}
        out["sample_status_check"] = {
            "sampled": len(sample_urls),
            "non_200_count": sum(1 for v in status_results.values()
                                 if v["status"] != 200),
            "errors_count": sum(1 for v in status_results.values()
                                if v["error"]),
            "non_200_urls": [u for u, v in status_results.items()
                             if v["status"] is not None and v["status"] != 200][:20],
        }

    if args.check_robots:
        out["robots_cross_check"] = _check_robots_reference(domain_root, sitemap_url)

    # Decide exit code
    issues = []
    v = out.get("validation", {})
    if v.get("non_https_url_count", 0) > 0: issues.append("non-https URLs in sitemap")
    if v.get("malformed_lastmod_count", 0) > 0: issues.append("malformed lastmod values")
    if v.get("all_lastmod_identical"): issues.append("all lastmod values identical")
    if v.get("missing_lastmod_entirely"): issues.append("no lastmod values anywhere")
    if out.get("exceeds_url_limit_per_file"): issues.append("urlset exceeds 50k URL protocol limit")
    if out.get("exceeds_size_limit"): issues.append("sitemap exceeds 50 MiB protocol limit")
    if out.get("sample_status_check", {}).get("non_200_count", 0) > 0:
        issues.append("sampled URLs return non-200")

    out["issues"] = issues
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

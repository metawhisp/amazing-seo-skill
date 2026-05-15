#!/usr/bin/env python3
"""
Broken-link checker for a single page.

Why it matters for SEO:
  - Google's official guidance: "Pages with many 404 links to and from
    them are not a good user experience" (Search Central docs).
  - Broken outbound links erode E-E-A-T trust signals — Quality Rater
    Guidelines flag pages with many broken citations as "Low Quality".
  - Broken internal links waste crawl budget and prevent link equity
    from flowing through the site.
  - For programmatic / template-driven pages, a single bad placeholder
    URL can produce thousands of broken links at scale.

What this script does:
  1. Fetches the target URL via the shared `_fetch.py` helper (realistic
     UA, SSRF guard, retries).
  2. Extracts every <a href>, <link rel="canonical|alternate|stylesheet">,
     <script src>, <img src>, <source src/srcset>, <video src>, and
     <iframe src> on the page. De-dupes by absolute URL.
  3. Splits links into internal (same host) and external (different host).
  4. Probes each unique link with HEAD (GET fallback for 405/403); reports
     status, redirect chain length, and final URL.
  5. Classifies findings: 4xx broken (P0), 5xx server errors (P1),
     redirects 3xx (P2 if chain > 1 or 301/302 mix), unreachable (P0).

Tunable:
  --max-links N      Cap total links probed (default 200)
  --internal-only    Skip external link probing
  --external-only    Skip internal probing
  --workers N        Concurrency (default 8)

Exit code:
  0 = no broken links found
  1 = fetch of target URL failed
  2 = at least one broken link found

Usage:
  broken_links_checker.py <url> [--max-links 200] [--internal-only]
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from _fetch import fetch


def _extract_all_links(html: str, base_url: str) -> list[dict]:
    """Pull every URL reference from the page. Returns [{kind, url}]."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    found: list[dict] = []

    def _push(kind: str, raw: str | None):
        if not raw:
            return
        raw = raw.strip()
        if not raw or raw.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            return
        absolute = urljoin(base_url, raw).split("#", 1)[0]
        found.append({"kind": kind, "url": absolute})

    for tag in soup.find_all("a"):
        _push("anchor", tag.get("href"))
    for tag in soup.find_all("link"):
        rel = " ".join(tag.get("rel") or []).lower()
        _push(f"link[{rel or 'unknown'}]", tag.get("href"))
    for tag in soup.find_all("script", src=True):
        _push("script", tag.get("src"))
    for tag in soup.find_all("img", src=True):
        _push("img", tag.get("src"))
    for tag in soup.find_all("source"):
        _push("source", tag.get("src") or tag.get("srcset", "").split(",")[0].strip().split()[0] if tag.get("srcset") else tag.get("src"))
    for tag in soup.find_all("iframe", src=True):
        _push("iframe", tag.get("src"))
    for tag in soup.find_all("video", src=True):
        _push("video", tag.get("src"))

    # De-dupe preserving order
    seen: set[str] = set()
    dedup: list[dict] = []
    for f in found:
        if f["url"] in seen:
            continue
        seen.add(f["url"])
        dedup.append(f)
    return dedup


def _probe(url: str) -> dict:
    """HEAD with GET fallback. Returns status, final_url, redirects, error."""
    try:
        r = requests.head(
            url, timeout=10, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; amazing-seo-skill/broken-links)"},
        )
        if r.status_code in (405, 403, 501) or r.status_code >= 500:
            r = fetch(url, timeout=10)
        return {
            "status": r.status_code,
            "final_url": r.url if r.url != url else None,
            "redirect_count": len(r.history),
            "error": None,
        }
    except requests.RequestException as e:
        return {"status": None, "final_url": None, "redirect_count": 0,
                "error": str(e)[:200]}


def _classify(status: int | None, redirect_count: int) -> str:
    if status is None:
        return "unreachable"
    if status >= 500:
        return "5xx_server_error"
    if status == 410:
        return "410_gone"
    # 401/403/429 are auth/rate-limit signals, not "broken". Many sites
    # gate bot HEAD requests this way (Claude.ai, paywalls, region-locked).
    # Surface separately so users can manually verify, not auto-P0.
    if status in (401, 403, 429):
        return "auth_or_rate_limited"
    if status >= 400:
        return "4xx_broken"
    if status >= 300:
        return "3xx_redirect"
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--max-links", type=int, default=200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--internal-only", action="store_true")
    ap.add_argument("--external-only", action="store_true")
    args = ap.parse_args()

    try:
        r = fetch(args.url, timeout=15)
    except requests.RequestException as e:
        print(json.dumps({"url": args.url, "error": str(e)}, indent=2))
        return 1

    target_host = urlparse(r.url).netloc
    links = _extract_all_links(r.text, r.url)

    # Partition internal vs external
    for link in links:
        link["internal"] = urlparse(link["url"]).netloc == target_host

    if args.internal_only:
        links = [l for l in links if l["internal"]]
    if args.external_only:
        links = [l for l in links if not l["internal"]]

    if len(links) > args.max_links:
        links_to_probe = links[:args.max_links]
        truncated = True
    else:
        links_to_probe = links
        truncated = False

    # Concurrent probing
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {pool.submit(_probe, l["url"]): l for l in links_to_probe}
        for fut in as_completed(future_map):
            link = future_map[fut]
            probe = fut.result()
            verdict = _classify(probe["status"], probe["redirect_count"])
            results.append({
                "url": link["url"],
                "kind": link["kind"],
                "internal": link["internal"],
                "status": probe["status"],
                "final_url": probe["final_url"],
                "redirect_count": probe["redirect_count"],
                "verdict": verdict,
                "error": probe["error"],
            })

    # Buckets
    broken_4xx = [r for r in results if r["verdict"] == "4xx_broken"]
    broken_410 = [r for r in results if r["verdict"] == "410_gone"]
    server_5xx = [r for r in results if r["verdict"] == "5xx_server_error"]
    unreachable = [r for r in results if r["verdict"] == "unreachable"]
    redirects = [r for r in results if r["verdict"] == "3xx_redirect"]
    auth_or_rate = [r for r in results if r["verdict"] == "auth_or_rate_limited"]

    out: dict = {
        "url": r.url,
        "http_status": r.status_code,
        "total_links_on_page": len(links),
        "links_probed": len(links_to_probe),
        "truncated": truncated,
        "summary": {
            "4xx_broken": len(broken_4xx),
            "410_gone": len(broken_410),
            "5xx_server_error": len(server_5xx),
            "unreachable": len(unreachable),
            "3xx_redirect": len(redirects),
            "auth_or_rate_limited": len(auth_or_rate),
            "ok": sum(1 for r in results if r["verdict"] == "ok"),
        },
        "broken_links": broken_4xx + broken_410,
        "server_errors": server_5xx,
        "unreachable": unreachable[:20],
        "redirects": redirects[:20],
        "needs_manual_verification": auth_or_rate[:20],
    }

    issues = []
    if broken_4xx:
        issues.append(f"{len(broken_4xx)} broken 4xx links (P0)")
    if broken_410:
        issues.append(f"{len(broken_410)} 410-Gone links (P1)")
    if server_5xx:
        issues.append(f"{len(server_5xx)} 5xx-error links (P1)")
    if unreachable:
        issues.append(f"{len(unreachable)} unreachable links (P1)")
    if len(redirects) > 5:
        issues.append(f"{len(redirects)} redirected links (P2; update to final URLs)")

    out["issues"] = issues
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if (broken_4xx or broken_410 or server_5xx or unreachable) else 0


if __name__ == "__main__":
    sys.exit(main())

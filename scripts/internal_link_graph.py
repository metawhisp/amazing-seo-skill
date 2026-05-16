#!/usr/bin/env python3
"""
Internal link graph builder + orphan detector.

Crawls a site starting from a seed URL (typically the homepage), follows only
same-host internal links up to a configurable depth, builds an in-memory
adjacency map, then cross-references against an XML sitemap to identify:

  - URLs in sitemap but NEVER linked from any crawled page (true orphans)
  - URLs linked from crawled pages but NOT in sitemap (sitemap gaps)
  - Pages with high link depth (>= 4 clicks from root, low crawl priority)
  - Hub pages (top in-degree) and dead-end pages (zero out-links)

Outputs JSON with the full graph + analysis.

Usage:
    internal_link_graph.py <seed_url> [--sitemap <url>] [--max-pages N] [--max-depth N]

Example:
    internal_link_graph.py https://example.com --max-pages 200 --max-depth 4
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict, deque
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from _fetch import fetch


def normalize_url(url: str) -> str:
    p = urlparse(url)
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{p.scheme}://{p.netloc}{path}"


def extract_links(html: str, base_url: str, host: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        p = urlparse(absolute)
        if p.netloc != host:
            continue
        out.append(normalize_url(absolute.split("#", 1)[0]))
    return out


def fetch_sitemap_urls(sitemap_url: str) -> set[str]:
    try:
        r = fetch(sitemap_url)
        soup = BeautifulSoup(r.text, "xml")
        urls: set[str] = set()
        # Sitemap index — recurse
        for sm in soup.find_all("sitemap"):
            loc = sm.find("loc")
            if loc:
                urls.update(fetch_sitemap_urls(loc.text.strip()))
        # urlset
        for u in soup.find_all("url"):
            loc = u.find("loc")
            if loc:
                urls.add(normalize_url(loc.text.strip()))
        return urls
    except Exception as e:
        print(f"WARN: sitemap fetch failed {sitemap_url}: {e}", file=sys.stderr)
        return set()


def crawl(seed: str, max_pages: int, max_depth: int, polite_delay: float = 0.3):
    seed = normalize_url(seed)
    host = urlparse(seed).netloc
    queue: deque[tuple[str, int]] = deque([(seed, 0)])
    visited: dict[str, dict] = {}
    edges: dict[str, list[str]] = defaultdict(list)

    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        try:
            r = fetch(url)
        except requests.RequestException:
            visited[url] = {"depth": depth, "status": "error", "out_links": 0}
            continue

        if r.status_code >= 400:
            visited[url] = {"depth": depth, "status": r.status_code, "out_links": 0}
            continue

        if "html" not in r.headers.get("content-type", "").lower():
            visited[url] = {"depth": depth, "status": r.status_code, "out_links": 0}
            continue

        links = list(set(extract_links(r.text, url, host)))
        visited[url] = {"depth": depth, "status": r.status_code, "out_links": len(links)}
        edges[url] = links

        if depth < max_depth:
            for child in links:
                if child not in visited:
                    queue.append((child, depth + 1))

        time.sleep(polite_delay)

    return visited, edges


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("seed")
    ap.add_argument("--sitemap")
    ap.add_argument("--max-pages", type=int, default=200)
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.3)
    args = ap.parse_args()

    sitemap_url = args.sitemap or f"{normalize_url(args.seed)}/sitemap.xml"
    sitemap_urls = fetch_sitemap_urls(sitemap_url)

    visited, edges = crawl(args.seed, args.max_pages, args.max_depth, args.delay)
    crawled = set(visited.keys())
    inbound: dict[str, int] = defaultdict(int)
    for src, targets in edges.items():
        for t in targets:
            inbound[t] += 1

    true_orphans = sorted(sitemap_urls - {u for u, info in visited.items()
                                          if str(info.get("status", "")).startswith("2")})
    sitemap_gaps = sorted(crawled - sitemap_urls)
    deep_pages = sorted([u for u, info in visited.items() if info["depth"] >= 4])
    hubs = sorted(inbound.items(), key=lambda x: -x[1])[:15]
    dead_ends = sorted([u for u, info in visited.items() if info.get("out_links", 0) == 0
                        and str(info.get("status", "")).startswith("2")])

    out = {
        "seed": args.seed,
        "sitemap_url": sitemap_url,
        "sitemap_url_count": len(sitemap_urls),
        "crawled_count": len(visited),
        "max_depth_reached": max((info["depth"] for info in visited.values()), default=0),
        "true_orphans": {
            "count": len(true_orphans),
            "urls": true_orphans[:50],
        },
        "sitemap_gaps": {
            "count": len(sitemap_gaps),
            "urls": sitemap_gaps[:50],
        },
        "deep_pages_depth_4plus": {
            "count": len(deep_pages),
            "urls": deep_pages[:30],
        },
        "top_hub_pages": [{"url": u, "in_degree": d} for u, d in hubs],
        "dead_end_pages": {
            "count": len(dead_ends),
            "urls": dead_ends[:30],
        },
    }
    # Exit code: 2 if findings (orphans, sitemap gaps, dead-ends),
    # 0 if clean. Consistent with other checkers.
    has_issues = (
        len(true_orphans) > 0
        or len(sitemap_gaps) > 0
        or len(dead_ends) > 0
    )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if has_issues else 0


if __name__ == "__main__":
    sys.exit(main())

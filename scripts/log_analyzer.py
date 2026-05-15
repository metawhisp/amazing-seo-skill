#!/usr/bin/env python3
"""
Server access-log analyser for SEO crawl behaviour.

Why it matters (Searchengineland 2026 guide):
  - Log analysis is the only way to see what Googlebot *actually* does
    on your site — not what GSC reports, not what your sitemap implies.
  - Reveals crawl-budget waste: pages crawled but useless, parameter
    duplicates, redirect chains burning quota.
  - Spots orphan pages (in logs but not linked), zombie pages (crawled
    but never indexed), and freshness gaps (high-value URLs not visited
    in 30+ days).
  - Detects bot abuse: AI crawlers (GPTBot, ClaudeBot, PerplexityBot)
    hammering low-value URLs, or fake bots spoofing real ones.

Supports:
  - Apache Combined log format (CLF + referrer + UA)
  - Nginx default format (same shape)
  - Auto-detect: if no `--format` flag, tries both
  - Gzipped logs: `.gz` files auto-decompressed

Reports:
  - Total requests, unique URLs, unique IPs
  - Per-bot breakdown (Googlebot, Bingbot, GPTBot, ClaudeBot, etc.)
  - Top 30 most-crawled URLs by Googlebot
  - Crawl waste candidates: high-frequency low-value paths (`?utm=*`,
    feeds, calendar archives, parameter explosions)
  - Status-code distribution per bot
  - 404 and 5xx spikes by date
  - Pages visited by Googlebot but not in sitemap (orphans, if sitemap provided)
  - "Cold" pages: in sitemap but not seen by Googlebot in N days

Exit code:
  0 = parsed cleanly, no critical findings
  1 = log file unreadable / format unrecognised
  2 = findings detected (waste, spikes, cold pages)

Usage:
  log_analyzer.py <log_file> [--sitemap URL] [--days 30] [--bot Googlebot]
  log_analyzer.py /var/log/nginx/access.log
  log_analyzer.py access.log.gz --sitemap https://example.com/sitemap.xml --days 90
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from _fetch import fetch


# Apache Combined / Nginx default:
# IP - - [DD/Mon/YYYY:HH:MM:SS +TZ] "METHOD /path HTTP/1.x" STATUS BYTES "REFERRER" "UA"
_LOG_RE = re.compile(
    r'(?P<ip>\S+)\s+\S+\s+\S+\s+'
    r'\[(?P<ts>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<url>[^"]*)\s+HTTP/\S+"\s+'
    r'(?P<status>\d+)\s+(?P<bytes>\S+)\s+'
    r'"(?P<referrer>[^"]*)"\s+'
    r'"(?P<ua>[^"]*)"'
)

# Bot taxonomy (user-agent substring → canonical name)
_BOT_RULES = [
    ("Googlebot",       ["Googlebot", "Storebot-Google"]),
    ("Google-Inspection", ["Google-InspectionTool"]),
    ("Bingbot",         ["bingbot", "BingPreview"]),
    ("GPTBot",          ["GPTBot"]),
    ("OAI-SearchBot",   ["OAI-SearchBot"]),
    ("ChatGPT-User",    ["ChatGPT-User"]),
    ("ClaudeBot",       ["ClaudeBot", "Claude-User", "anthropic-ai", "Claude-Web"]),
    ("PerplexityBot",   ["PerplexityBot", "Perplexity-User"]),
    ("Applebot",        ["Applebot"]),
    ("Bytespider",      ["Bytespider"]),
    ("CCBot",           ["CCBot"]),
    ("Cohere",          ["cohere-ai"]),
    ("DuckDuckBot",     ["DuckDuckBot"]),
    ("YandexBot",       ["YandexBot"]),
    ("Baiduspider",     ["Baiduspider"]),
    ("Diffbot",         ["Diffbot"]),
    ("Meta",            ["meta-externalagent", "meta-externalfetcher", "FacebookBot"]),
]


def _classify_bot(ua: str) -> str:
    for canon, tokens in _BOT_RULES:
        for tok in tokens:
            if tok in ua:
                return canon
    return "Other"


def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        return None


def _open_log(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def _is_crawl_waste(url: str) -> str | None:
    """Heuristic: identify URLs that almost certainly waste crawl budget."""
    lower = url.lower()
    if re.search(r"[?&]utm_", lower):
        return "UTM parameter (filter via canonical or robots)"
    if re.search(r"[?&](sessionid|sid|phpsessid|fbclid|gclid|ref|source)=", lower):
        return "Tracking parameter (canonical away)"
    if "/feed/" in lower or lower.endswith("/feed") or "/rss" in lower:
        return "RSS/feed URL (low SEO value, consider robots.txt block)"
    if "/calendar/" in lower or "/archive/" in lower:
        return "Calendar/archive (infinite pagination risk)"
    if "/wp-json/" in lower or "/api/" in lower:
        return "API endpoint (not for indexing)"
    if "?page=" in lower and re.search(r"page=([5-9]|\d{2,})", lower):
        return "Deep pagination (page 5+ often low-value)"
    if "?" in lower and lower.count("&") > 3:
        return "Heavy parameter URL (likely duplicate)"
    return None


def _fetch_sitemap_urls(sitemap_url: str) -> set[str]:
    from urllib.parse import urlparse
    try:
        r = fetch(sitemap_url, timeout=15)
        if not r.ok:
            return set()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "xml")
        urls: set[str] = set()
        # Recurse sitemap index
        for sm in soup.find_all("sitemap"):
            loc = sm.find("loc")
            if loc:
                urls.update(_fetch_sitemap_urls(loc.text.strip()))
        for u in soup.find_all("url"):
            loc = u.find("loc")
            if loc:
                # Normalise: keep path only for matching against log URLs
                path = urlparse(loc.text.strip()).path or "/"
                urls.add(path)
        return urls
    except Exception:
        return set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("log_file")
    ap.add_argument("--sitemap", help="sitemap URL to cross-check (finds orphans/cold pages)")
    ap.add_argument("--days", type=int, default=30,
                    help="window for 'cold pages' check (default 30 days)")
    ap.add_argument("--bot", default="Googlebot",
                    help="primary bot to focus on (default: Googlebot)")
    args = ap.parse_args()

    log_path = Path(args.log_file)
    if not log_path.exists():
        print(json.dumps({"error": f"log file not found: {log_path}"}, indent=2))
        return 1

    # ── Parse ────────────────────────────────────────────────────────────
    bot_hits: Counter[str] = Counter()
    bot_url_hits: defaultdict[str, Counter[str]] = defaultdict(Counter)
    bot_status_dist: defaultdict[str, Counter[int]] = defaultdict(Counter)
    daily_4xx: Counter[str] = Counter()
    daily_5xx: Counter[str] = Counter()
    total_parsed = 0
    total_lines = 0
    unique_ips: set[str] = set()
    waste_url_counts: Counter[str] = Counter()
    waste_url_reasons: dict[str, str] = {}
    last_seen_by_url: dict[str, datetime] = {}

    with _open_log(log_path) as f:
        for line in f:
            total_lines += 1
            m = _LOG_RE.match(line)
            if not m:
                continue
            total_parsed += 1
            ua = m["ua"]
            url = m["url"]
            status = int(m["status"])
            ip = m["ip"]
            ts = _parse_ts(m["ts"])
            bot = _classify_bot(ua)

            unique_ips.add(ip)
            bot_hits[bot] += 1
            bot_url_hits[bot][url] += 1
            bot_status_dist[bot][status] += 1

            if ts:
                day = ts.date().isoformat()
                if 400 <= status < 500:
                    daily_4xx[day] += 1
                elif 500 <= status < 600:
                    daily_5xx[day] += 1
                if bot == args.bot:
                    if url not in last_seen_by_url or ts > last_seen_by_url[url]:
                        last_seen_by_url[url] = ts

            # Identify waste from primary bot's perspective
            if bot == args.bot:
                reason = _is_crawl_waste(url)
                if reason:
                    waste_url_counts[url] += 1
                    waste_url_reasons[url] = reason

    if total_parsed == 0:
        print(json.dumps({
            "log_file": str(log_path),
            "total_lines": total_lines,
            "error": "no log lines matched Apache/Nginx combined format",
        }, indent=2))
        return 1

    # ── Aggregates ───────────────────────────────────────────────────────
    primary_bot = args.bot
    bot_summary = [
        {"bot": b, "requests": n, "share_pct": round(100 * n / total_parsed, 1)}
        for b, n in bot_hits.most_common(20)
    ]
    primary_top_urls = bot_url_hits[primary_bot].most_common(30)

    # Crawl waste: URLs from primary bot matching waste heuristics
    waste = sorted(waste_url_counts.items(), key=lambda x: -x[1])[:30]
    waste_total_hits = sum(waste_url_counts.values())
    waste_share_pct = round(100 * waste_total_hits / max(1, bot_hits[primary_bot]), 1)

    # Status distribution
    primary_status = dict(bot_status_dist[primary_bot])
    primary_4xx = sum(c for s, c in primary_status.items() if 400 <= s < 500)
    primary_5xx = sum(c for s, c in primary_status.items() if 500 <= s < 600)

    # Daily error spikes (highest 5 days)
    spikes_4xx = sorted(daily_4xx.items(), key=lambda x: -x[1])[:5]
    spikes_5xx = sorted(daily_5xx.items(), key=lambda x: -x[1])[:5]

    # Sitemap cross-check
    orphan_findings: list[str] = []
    cold_findings: list[str] = []
    if args.sitemap:
        sitemap_paths = _fetch_sitemap_urls(args.sitemap)
        from urllib.parse import urlparse
        crawled_paths = {urlparse(u).path for u in bot_url_hits[primary_bot] if u.startswith("/")}
        # Orphans: crawled by primary bot but not in sitemap
        orphans = crawled_paths - sitemap_paths
        orphan_findings = sorted(orphans)[:20]

        # Cold: in sitemap but last_seen older than --days
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        for path in sitemap_paths:
            seen = last_seen_by_url.get(path)
            if seen is None or seen < cutoff:
                cold_findings.append(path)
        cold_findings = sorted(cold_findings)[:30]

    issues = []
    if waste_share_pct > 15:
        issues.append(f"{waste_share_pct}% of {primary_bot} hits are crawl waste (>{15}% threshold)")
    if primary_5xx > 0:
        issues.append(f"{primary_5xx} 5xx responses served to {primary_bot}")
    if primary_4xx > 0 and bot_hits[primary_bot] > 0:
        pct_4xx = round(100 * primary_4xx / bot_hits[primary_bot], 1)
        if pct_4xx > 5:
            issues.append(f"{pct_4xx}% of {primary_bot} requests returned 4xx")
    if cold_findings and args.sitemap:
        issues.append(f"{len(cold_findings)} sitemap URLs not crawled by {primary_bot} in {args.days} days")

    out = {
        "log_file": str(log_path),
        "total_lines": total_lines,
        "lines_parsed": total_parsed,
        "parse_rate_pct": round(100 * total_parsed / max(1, total_lines), 1),
        "unique_ips": len(unique_ips),
        "bot_summary": bot_summary,
        "primary_bot": primary_bot,
        "primary_bot_top_urls": [{"url": u[:140], "hits": n} for u, n in primary_top_urls],
        "primary_bot_status_distribution": primary_status,
        "primary_bot_4xx_count": primary_4xx,
        "primary_bot_5xx_count": primary_5xx,
        "crawl_waste": {
            "total_waste_hits": waste_total_hits,
            "share_pct": waste_share_pct,
            "top_waste_urls": [
                {"url": u[:140], "hits": n, "reason": waste_url_reasons[u]}
                for u, n in waste
            ],
        },
        "daily_4xx_spikes": [{"date": d, "count": c} for d, c in spikes_4xx],
        "daily_5xx_spikes": [{"date": d, "count": c} for d, c in spikes_5xx],
        "sitemap_cross_check": {
            "orphan_urls_crawled_but_not_in_sitemap": orphan_findings,
            "cold_urls_in_sitemap_not_crawled": cold_findings,
        } if args.sitemap else None,
        "issues": issues,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

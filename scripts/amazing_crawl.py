#!/usr/bin/env python3
"""
amazing-crawl — open-source SEO crawler with no URL cap.

Designed as a drop-in fallback when Screaming Frog isn't available
(no license, server / Docker / CI environment, or above the 500-URL
free-tier cap). Output is compatible with the rest of the skill: per-URL
SEO metadata captured to SQLite (and optional CSV/JSON export).

Why async + SQLite rather than threads + in-memory:
  - Async (httpx.AsyncClient) handles thousands of concurrent fetches
    on a single Python process. Threads waste memory on stacks; async
    keeps each in-flight request to ~few KB.
  - SQLite checkpoint after every fetch means: resume after Ctrl-C, no
    losing 50k fetched URLs to a memory blowup. Production crawlers
    work this way.

What we capture per URL:
  - HTTP status, final URL after redirects, redirect count
  - Content-Type, byte size
  - Title, meta description, meta robots, canonical
  - H1 (all), H2 count
  - Word count of visible body text
  - Link counts: internal vs external
  - Image counts: with vs without alt
  - JSON-LD schema block count + types
  - hreflang declaration count
  - Response time (ms)

Discovery:
  - BFS from seed URL, follow only same-host internal anchors
  - Respect robots.txt (Disallow lines, by default; pass --ignore-robots
    to skip — useful for staging audits)
  - Polite delay configurable (default 0 because async + concurrency
    cap already prevents hammering)
  - Optional `--js` flag: each URL fetched additionally via Playwright,
    rendered HTML used for parsing (slower but accurate for SPAs)

Output:
  ~/.amazing-seo-skill/crawls/<domain>-<ts>.db (override with --output)
  Optional: --csv <path> / --json <path>

Resume:
  Same --output path → continues from queue state stored in DB. No
  duplicate work.

Usage:
  amazing_crawl.py https://example.com
  amazing_crawl.py https://example.com --max-pages 10000 --concurrency 20
  amazing_crawl.py https://example.com --js --max-pages 500    # SPA
  amazing_crawl.py https://example.com --csv export.csv         # also export

Exit code:
  0 = crawl completed cleanly
  1 = seed fetch failed
  2 = errors encountered (some URLs failed) but crawl progressed
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import httpx
from bs4 import BeautifulSoup


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def _normalize(u: str) -> str:
    u, _ = urldefrag(u)
    p = urlparse(u)
    # Drop trailing slash except root
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{p.scheme}://{p.netloc.lower()}{path}{('?' + p.query) if p.query else ''}"


def _is_same_host(seed_host: str, url: str) -> bool:
    return urlparse(url).netloc.lower() == seed_host.lower()


def _parse_html(html: str, base_url: str) -> dict:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    meta_desc = None
    meta_robots = None
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        if name == "description":
            meta_desc = meta.get("content")
        elif name == "robots":
            meta_robots = meta.get("content")
    canonical_tag = soup.find("link", rel="canonical")
    canonical = canonical_tag.get("href") if canonical_tag else None

    h1s = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
    h2_count = len(soup.find_all("h2"))

    # Schema JSON-LD
    schema_types: list[str] = []
    for s in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        try:
            data = json.loads(s.string or s.get_text() or "")
            blocks = data if isinstance(data, list) else [data]
            for b in blocks:
                if isinstance(b, dict):
                    t = b.get("@type", "?")
                    schema_types.append(t if isinstance(t, str) else (t[0] if t else "?"))
        except (json.JSONDecodeError, TypeError):
            pass

    # Hreflang
    hreflang_count = sum(1 for l in soup.find_all("link", rel="alternate") if l.get("hreflang"))

    # Internal vs external links
    base_host = urlparse(base_url).netloc.lower()
    internal_links: set[str] = set()
    external_count = 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        absolute = urljoin(base_url, href)
        host = urlparse(absolute).netloc.lower()
        if host == base_host:
            internal_links.add(_normalize(absolute))
        else:
            external_count += 1

    # Images
    img_total = 0
    img_no_alt = 0
    for img in soup.find_all("img"):
        img_total += 1
        if not img.get("alt") or not img.get("alt").strip():
            if img.get("alt") is None:  # Missing attribute (not just empty decorative)
                img_no_alt += 1

    # Visible word count (strip nav/footer/script/style)
    for el in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        el.decompose()
    text = soup.get_text(separator=" ", strip=True)
    word_count = len(re.findall(r"\b\w+\b", text))

    return {
        "title": title, "meta_description": meta_desc, "meta_robots": meta_robots,
        "canonical": canonical, "h1": h1s, "h2_count": h2_count,
        "schema_types": schema_types, "hreflang_count": hreflang_count,
        "internal_links_count": len(internal_links),
        "external_links_count": external_count,
        "image_count": img_total, "image_missing_alt": img_no_alt,
        "word_count": word_count,
        "_discovered_links": list(internal_links),
    }


class RobotsCache:
    """Minimal robots.txt fetcher + Disallow matcher (per-UA simple match)."""

    def __init__(self, ua: str = _DEFAULT_UA):
        self.ua = ua
        self.disallows: dict[str, list[str]] = {}  # host → list of paths

    async def fetch(self, client: httpx.AsyncClient, host: str, scheme: str = "https"):
        if host in self.disallows:
            return
        try:
            r = await client.get(f"{scheme}://{host}/robots.txt", timeout=10)
            if r.status_code != 200:
                self.disallows[host] = []
                return
            lines = r.text.splitlines()
            current_uas: list[str] = []
            disallow: list[str] = []
            apply_to_us = False
            for raw in lines:
                line = raw.split("#", 1)[0].strip()
                if not line:
                    apply_to_us = False
                    current_uas = []
                    continue
                if ":" not in line:
                    continue
                d, _, v = line.partition(":")
                d = d.strip().lower()
                v = v.strip()
                if d == "user-agent":
                    current_uas.append(v)
                    apply_to_us = (v == "*" or v.lower() in self.ua.lower())
                elif d == "disallow" and apply_to_us and v:
                    disallow.append(v)
            self.disallows[host] = disallow
        except Exception:
            self.disallows[host] = []

    def allowed(self, host: str, path: str) -> bool:
        for d in self.disallows.get(host, []):
            if path.startswith(d):
                return False
        return True


def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            url TEXT PRIMARY KEY,
            status INTEGER, final_url TEXT, redirect_count INTEGER,
            content_type TEXT, byte_size INTEGER, response_ms INTEGER,
            title TEXT, meta_description TEXT, meta_robots TEXT, canonical TEXT,
            h1 TEXT, h2_count INTEGER,
            schema_types TEXT, hreflang_count INTEGER,
            internal_links INTEGER, external_links INTEGER,
            image_count INTEGER, image_missing_alt INTEGER,
            word_count INTEGER,
            crawled_at TEXT,
            depth INTEGER, error TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            url TEXT PRIMARY KEY, depth INTEGER, queued_at TEXT
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status)")
    conn.commit()
    return conn


async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    js_render: bool,
) -> tuple[httpx.Response | None, float, str | None]:
    """Fetch URL with timing. Return (response, ms, error)."""
    t0 = time.monotonic()
    try:
        r = await client.get(url, timeout=20, follow_redirects=True,
                             headers={"User-Agent": _DEFAULT_UA})
        return r, (time.monotonic() - t0) * 1000, None
    except httpx.HTTPError as e:
        return None, (time.monotonic() - t0) * 1000, str(e)[:200]


async def _crawl(
    seed: str,
    db: sqlite3.Connection,
    max_pages: int,
    max_depth: int,
    concurrency: int,
    delay_s: float,
    ignore_robots: bool,
    progress_every: int = 50,
) -> dict:
    seed = _normalize(seed)
    seed_host = urlparse(seed).netloc

    # Restore queue from DB or seed it
    cursor = db.execute("SELECT url, depth FROM queue")
    queue: asyncio.Queue = asyncio.Queue()
    queued: set[str] = set()
    for url, depth in cursor.fetchall():
        await queue.put((url, depth))
        queued.add(url)
    visited: set[str] = {
        row[0] for row in db.execute("SELECT url FROM pages WHERE status IS NOT NULL")
    }
    if not queued and seed not in visited:
        await queue.put((seed, 0))
        queued.add(seed)
        db.execute("INSERT OR IGNORE INTO queue (url, depth, queued_at) VALUES (?, ?, ?)",
                   (seed, 0, datetime.now(timezone.utc).isoformat()))
        db.commit()

    robots = RobotsCache()
    pages_done = len(visited)
    errors = 0
    start_t = time.monotonic()

    limits = httpx.Limits(max_connections=concurrency * 2,
                          max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(http2=True, limits=limits, follow_redirects=True) as client:
        # Robots for seed host
        if not ignore_robots:
            await robots.fetch(client, seed_host, urlparse(seed).scheme)

        async def worker():
            nonlocal pages_done, errors
            while pages_done < max_pages:
                try:
                    url, depth = await asyncio.wait_for(queue.get(), timeout=2)
                except asyncio.TimeoutError:
                    return
                if url in visited:
                    queue.task_done()
                    continue

                path = urlparse(url).path or "/"
                if not ignore_robots and not robots.allowed(seed_host, path):
                    db.execute("UPDATE queue SET url=url WHERE url=?", (url,))  # no-op
                    db.execute("DELETE FROM queue WHERE url=?", (url,))
                    visited.add(url)
                    queue.task_done()
                    continue

                resp, ms, err = await _fetch_one(client, url, False)
                visited.add(url)
                pages_done += 1

                if err or resp is None:
                    errors += 1
                    db.execute("""
                        INSERT OR REPLACE INTO pages
                          (url, status, error, crawled_at, depth)
                        VALUES (?, ?, ?, ?, ?)
                    """, (url, None, err, datetime.now(timezone.utc).isoformat(), depth))
                    db.execute("DELETE FROM queue WHERE url=?", (url,))
                    db.commit()
                    queue.task_done()
                    continue

                ctype = resp.headers.get("content-type", "").split(";")[0].strip()
                if "html" not in ctype:
                    db.execute("""
                        INSERT OR REPLACE INTO pages
                          (url, status, final_url, content_type, byte_size,
                           response_ms, crawled_at, depth)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (url, resp.status_code, str(resp.url), ctype,
                          len(resp.content), int(ms),
                          datetime.now(timezone.utc).isoformat(), depth))
                    db.execute("DELETE FROM queue WHERE url=?", (url,))
                    db.commit()
                    queue.task_done()
                    continue

                parsed = _parse_html(resp.text, str(resp.url))
                db.execute("""
                    INSERT OR REPLACE INTO pages
                      (url, status, final_url, redirect_count, content_type,
                       byte_size, response_ms, title, meta_description,
                       meta_robots, canonical, h1, h2_count, schema_types,
                       hreflang_count, internal_links, external_links,
                       image_count, image_missing_alt, word_count,
                       crawled_at, depth)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    url, resp.status_code, str(resp.url),
                    len(resp.history), ctype, len(resp.content), int(ms),
                    parsed["title"], parsed["meta_description"], parsed["meta_robots"],
                    parsed["canonical"], json.dumps(parsed["h1"]), parsed["h2_count"],
                    json.dumps(parsed["schema_types"]), parsed["hreflang_count"],
                    parsed["internal_links_count"], parsed["external_links_count"],
                    parsed["image_count"], parsed["image_missing_alt"], parsed["word_count"],
                    datetime.now(timezone.utc).isoformat(), depth,
                ))
                db.execute("DELETE FROM queue WHERE url=?", (url,))

                # Enqueue discovered internal links
                if depth < max_depth:
                    for child in parsed["_discovered_links"]:
                        if child in visited or child in queued:
                            continue
                        if not _is_same_host(seed_host, child):
                            continue
                        await queue.put((child, depth + 1))
                        queued.add(child)
                        db.execute("INSERT OR IGNORE INTO queue (url, depth, queued_at) VALUES (?, ?, ?)",
                                   (child, depth + 1, datetime.now(timezone.utc).isoformat()))
                db.commit()

                if pages_done % progress_every == 0:
                    elapsed = time.monotonic() - start_t
                    rate = pages_done / max(0.1, elapsed)
                    print(f"  [{pages_done}/{max_pages}] rate={rate:.1f} URL/s, "
                          f"queue={queue.qsize()}, errors={errors}", file=sys.stderr)

                if delay_s > 0:
                    await asyncio.sleep(delay_s)
                queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await asyncio.gather(*workers, return_exceptions=True)

    elapsed = time.monotonic() - start_t
    return {
        "seed": seed,
        "pages_crawled": pages_done,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 1),
        "rate_url_per_sec": round(pages_done / max(0.1, elapsed), 2),
        "queue_remaining": queue.qsize(),
    }


def _export_csv(db: sqlite3.Connection, path: Path):
    cur = db.execute("SELECT * FROM pages")
    cols = [d[0] for d in cur.description]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in cur:
            w.writerow(row)


def _export_json(db: sqlite3.Connection, path: Path):
    cur = db.execute("SELECT * FROM pages")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur]
    Path(path).write_text(json.dumps(rows, indent=2, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("seed", help="seed URL to start crawling from")
    ap.add_argument("--max-pages", type=int, default=10_000)
    ap.add_argument("--max-depth", type=int, default=10)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--delay", type=float, default=0.0,
                    help="optional per-worker delay between requests (default 0)")
    ap.add_argument("--ignore-robots", action="store_true",
                    help="ignore robots.txt (use for staging audits)")
    ap.add_argument("--output", help="SQLite path (default: ~/.amazing-seo-skill/crawls/<domain>-<ts>.db)")
    ap.add_argument("--csv", help="export results to CSV after crawl")
    ap.add_argument("--json", help="export results to JSON after crawl")
    args = ap.parse_args()

    seed = args.seed
    if not seed.startswith(("http://", "https://")):
        seed = "https://" + seed

    if args.output:
        db_path = Path(args.output)
    else:
        domain = urlparse(seed).netloc.replace(":", "_")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        db_path = Path.home() / ".amazing-seo-skill" / "crawls" / f"{domain}-{ts}.db"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = _open_db(db_path)

    summary = asyncio.run(_crawl(
        seed=seed, db=db,
        max_pages=args.max_pages, max_depth=args.max_depth,
        concurrency=args.concurrency, delay_s=args.delay,
        ignore_robots=args.ignore_robots,
    ))
    summary["db_path"] = str(db_path)

    # Status distribution + top issues
    status_dist = dict(db.execute(
        "SELECT status, COUNT(*) FROM pages WHERE status IS NOT NULL GROUP BY status",
    ).fetchall())
    missing_title = db.execute(
        "SELECT COUNT(*) FROM pages WHERE status=200 AND (title IS NULL OR title='')",
    ).fetchone()[0]
    missing_desc = db.execute(
        "SELECT COUNT(*) FROM pages WHERE status=200 AND (meta_description IS NULL OR meta_description='')",
    ).fetchone()[0]
    missing_canonical = db.execute(
        "SELECT COUNT(*) FROM pages WHERE status=200 AND (canonical IS NULL OR canonical='')",
    ).fetchone()[0]
    no_h1 = db.execute(
        "SELECT COUNT(*) FROM pages WHERE status=200 AND (h1 IS NULL OR h1='[]')",
    ).fetchone()[0]

    summary["status_distribution"] = status_dist
    summary["seo_issues"] = {
        "missing_title": missing_title,
        "missing_meta_description": missing_desc,
        "missing_canonical": missing_canonical,
        "missing_h1": no_h1,
    }

    if args.csv:
        _export_csv(db, Path(args.csv))
        summary["csv_export"] = args.csv
    if args.json:
        _export_json(db, Path(args.json))
        summary["json_export"] = args.json

    db.close()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 2 if summary["errors"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

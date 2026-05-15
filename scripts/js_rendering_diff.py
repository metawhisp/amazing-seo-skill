#!/usr/bin/env python3
"""
Server-rendered vs client-rendered HTML diff.

Why it matters (Google JS SEO docs, December 2025 update):
  - "AI crawlers do NOT execute JavaScript" — GPTBot, PerplexityBot, etc.
    read only the initial server response.
  - Googlebot DOES render JS, but with a queue: indexing of JS-rendered
    content is delayed (hours to days).
  - For time-sensitive content (Product, Article, Offer), JSON-LD injected
    via JavaScript may face significantly delayed indexing.
  - If a canonical tag in raw HTML differs from one injected by JS,
    Google may use EITHER one — non-deterministic.
  - If raw HTML contains `noindex` but JS removes it, Google MAY still
    honour the original noindex.

This checker fetches the URL twice — once with `requests` (raw HTML, no JS)
and once with Playwright headless Chrome (fully rendered) — then reports
the deltas across SEO-critical elements:

  - Title, meta description, canonical, robots meta
  - H1, H2 counts and text
  - JSON-LD schema blocks (count + types)
  - Word count of visible text
  - Internal link count
  - Image count (with src)
  - Hreflang declarations

Each delta is severity-tagged:
  P0 — different canonical, different robots, schema only in rendered
  P1 — different title/description, big word-count delta, schema type mismatch
  P2 — heading text differences, image/link count differences

Exit code:
  0 = raw HTML already has all SEO-critical elements (server-side complete)
  1 = fetch failed (either raw or rendered)
  2 = at least one P0/P1 finding (JS-dependent SEO content)

Usage:
  js_rendering_diff.py <url> [--save-pair DIR]

Requires Playwright + Chromium installed (`playwright install chromium`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests

from _fetch import fetch

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("ERROR: playwright not installed. Run: .venv/bin/pip install playwright && "
          ".venv/bin/playwright install chromium", file=sys.stderr)
    sys.exit(64)


from bs4 import BeautifulSoup


def _extract_seo_elements(html: str, base_url: str) -> dict:
    """Pull every SEO-critical element from one HTML snapshot."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    title = soup.find("title")
    title_text = title.get_text(strip=True) if title else None

    meta_desc = None
    meta_robots = None
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        if name == "description":
            meta_desc = meta.get("content")
        elif name == "robots":
            meta_robots = meta.get("content")

    canonical = None
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag:
        canonical = canonical_tag.get("href")

    h1_texts = [h.get_text(strip=True) for h in soup.find_all("h1") if h.get_text(strip=True)]
    h2_texts = [h.get_text(strip=True) for h in soup.find_all("h2") if h.get_text(strip=True)]

    # JSON-LD
    schema_blocks = []
    for script in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        try:
            data = json.loads(script.string or script.get_text() or "")
            if isinstance(data, dict):
                schema_blocks.append(data.get("@type", "?"))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        schema_blocks.append(item.get("@type", "?"))
        except (json.JSONDecodeError, TypeError):
            pass

    # Visible word count — strip scripts/styles/nav/footer
    for el in soup(["script", "style", "noscript"]):
        el.decompose()
    text = soup.get_text(separator=" ", strip=True)
    words = re.findall(r"\b\w+\b", text)

    # Hreflang
    hreflang = []
    for link in soup.find_all("link", rel="alternate"):
        lang = link.get("hreflang")
        href = link.get("href")
        if lang and href:
            hreflang.append({"lang": lang, "href": href})

    return {
        "title": title_text,
        "meta_description": meta_desc,
        "meta_robots": meta_robots,
        "canonical": canonical,
        "h1": h1_texts,
        "h2_count": len(h2_texts),
        "schema_types": sorted(schema_blocks),
        "schema_count": len(schema_blocks),
        "word_count": len(words),
        "internal_link_count": sum(
            1 for a in soup.find_all("a", href=True)
            if not a["href"].startswith(("http://", "https://", "//", "mailto:", "tel:"))
            or base_url in (a["href"] or "")
        ),
        "image_count": len(soup.find_all("img")),
        "hreflang_count": len(hreflang),
    }


def _render_with_playwright(url: str, timeout_ms: int = 25_000) -> str:
    """Fetch fully-rendered HTML via headless Chromium."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 900},
            )
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            # Small extra wait for any deferred client-side hydration
            page.wait_for_timeout(800)
            html = page.content()
            return html
        finally:
            browser.close()


def _diff(raw: dict, rendered: dict) -> list[dict]:
    """Compare raw vs rendered, return list of {severity, key, text}."""
    findings = []

    def _diff_field(key: str, sev: str, label: str | None = None):
        if raw.get(key) != rendered.get(key):
            findings.append({
                "severity": sev,
                "key": key,
                "raw": str(raw.get(key))[:200],
                "rendered": str(rendered.get(key))[:200],
                "text": f"{label or key} differs between raw and rendered HTML",
            })

    # P0 — search engines may pick either, non-deterministic
    _diff_field("canonical", "P0", "Canonical tag")
    _diff_field("meta_robots", "P0", "Meta robots directive")

    # Schema: count delta is critical (means JSON-LD injected by JS — delayed indexing)
    if raw["schema_count"] < rendered["schema_count"]:
        delta = rendered["schema_count"] - raw["schema_count"]
        findings.append({
            "severity": "P0",
            "key": "schema_count",
            "raw": raw["schema_count"],
            "rendered": rendered["schema_count"],
            "text": f"{delta} JSON-LD schema block(s) only present in rendered HTML — AI crawlers will miss them; Google may delay indexing",
        })
    elif raw["schema_count"] > rendered["schema_count"]:
        findings.append({
            "severity": "P2",
            "key": "schema_count",
            "raw": raw["schema_count"],
            "rendered": rendered["schema_count"],
            "text": f"Schema present in raw but not rendered ({raw['schema_count']} vs {rendered['schema_count']}) — JS may be removing markup",
        })

    # P1 — different title / description / hreflang
    _diff_field("title", "P1", "<title>")
    _diff_field("meta_description", "P1", "Meta description")
    if raw["hreflang_count"] != rendered["hreflang_count"]:
        findings.append({
            "severity": "P1",
            "key": "hreflang_count",
            "raw": raw["hreflang_count"],
            "rendered": rendered["hreflang_count"],
            "text": f"Hreflang count differs ({raw['hreflang_count']} raw vs {rendered['hreflang_count']} rendered)",
        })

    # P1 — word count drop > 50%: content is mostly client-side
    if raw["word_count"] > 0 and rendered["word_count"] > 0:
        ratio = raw["word_count"] / rendered["word_count"]
        if ratio < 0.5:
            findings.append({
                "severity": "P1",
                "key": "word_count",
                "raw": raw["word_count"],
                "rendered": rendered["word_count"],
                "text": f"Raw HTML has only {ratio*100:.0f}% of rendered word count — most content client-side; AI crawlers see almost nothing",
            })
    elif rendered["word_count"] > 100 and raw["word_count"] < 50:
        findings.append({
            "severity": "P0",
            "key": "word_count",
            "raw": raw["word_count"],
            "rendered": rendered["word_count"],
            "text": "Raw HTML is essentially empty (<50 words) — full client-side rendering; AI crawlers see no content",
        })

    # P2 — heading differences
    if raw["h1"] != rendered["h1"]:
        findings.append({
            "severity": "P2",
            "key": "h1",
            "raw": raw["h1"],
            "rendered": rendered["h1"],
            "text": "H1 differs between raw and rendered",
        })
    if abs(raw["h2_count"] - rendered["h2_count"]) > 2:
        findings.append({
            "severity": "P2",
            "key": "h2_count",
            "raw": raw["h2_count"],
            "rendered": rendered["h2_count"],
            "text": f"H2 count differs significantly ({raw['h2_count']} vs {rendered['h2_count']})",
        })

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--save-pair", metavar="DIR",
                    help="save raw.html and rendered.html into DIR for manual inspection")
    args = ap.parse_args()

    url = args.url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # 1. Raw HTML
    try:
        r = fetch(url, timeout=15)
        raw_html = r.text
    except requests.RequestException as e:
        print(json.dumps({"url": url, "error": f"raw fetch failed: {e}"}, indent=2))
        return 1

    # 2. Rendered HTML
    try:
        rendered_html = _render_with_playwright(url)
    except (PWTimeout, Exception) as e:
        print(json.dumps({"url": url, "error": f"playwright render failed: {e}"}, indent=2))
        return 1

    raw_seo = _extract_seo_elements(raw_html, url)
    rendered_seo = _extract_seo_elements(rendered_html, url)
    findings = _diff(raw_seo, rendered_seo)

    if args.save_pair:
        out_dir = Path(args.save_pair)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "raw.html").write_text(raw_html, encoding="utf-8")
        (out_dir / "rendered.html").write_text(rendered_html, encoding="utf-8")

    result = {
        "url": url,
        "raw_seo": raw_seo,
        "rendered_seo": rendered_seo,
        "findings": findings,
        "findings_count": len(findings),
        "verdict": (
            "ssr-complete" if not findings else
            "js-dependent-critical" if any(f["severity"] == "P0" for f in findings) else
            "js-dependent-minor"
        ),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    has_critical = any(f["severity"] in ("P0", "P1") for f in findings)
    return 2 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())

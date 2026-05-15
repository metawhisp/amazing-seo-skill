#!/usr/bin/env python3
"""
Image-optimization deterministic audit for a single page.

Why it matters (verified May 2026):
  - Alt text is required for accessibility (WCAG 2.1 SC 1.1.1) and is
    used by Google Image Search for ranking.
  - Image formats: WebP ~95% browser support, AVIF ~94% (Safari iOS 16+),
    AVIF is 50% smaller than JPEG and 20-30% smaller than WebP at the
    same visual quality. Sources: Google WebP study, Can I Use, Web.dev.
  - LCP and CLS are Core Web Vitals — image format/size and missing
    `width`/`height` attributes are top causes of LCP regression and
    CLS layout shift.
  - Native `loading="lazy"` is sufficient in 2026; no JS-shim needed.
  - Google does NOT boost rankings for WebP/AVIF directly, but the
    LCP/CWV improvement is a ranking signal.

What this audit reports for every <img>, <source>, and CSS background:
  - Alt-text coverage: how many images have non-empty alt vs decorative
    `alt=""` vs missing
  - Format mix: jpeg, png, webp, avif, svg counts and percentages
  - Dimensions: width + height attributes present (CLS prevention)
  - Lazy-loading: `loading="lazy"` on below-fold images
  - File size: byte-size of each src (HEAD probe, concurrent)
  - LCP candidates: images larger than 200KB are flagged
  - Outliers: PNG photographs (should be JPEG/WebP), oversized JPEGs

Exit code:
  0 = no critical issues
  1 = fetch failed
  2 = at least one P0/P1 finding (missing alt, oversized images,
       missing dimensions)

Usage:
  images_audit.py <url> [--max-images N] [--no-size-probe]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from _fetch import fetch


# File-size thresholds (bytes) based on Web.dev image-best-practices guidance
_SIZE_WARN  = 200 * 1024     # 200 KB — noticeable LCP hit on slow networks
_SIZE_CRIT  = 500 * 1024     # 500 KB — almost certainly an LCP regression

# Format coverage thresholds (verified 2026 Can I Use)
_NEXT_GEN_TARGET_PCT = 70    # at least 70% of images should be WebP/AVIF/SVG


def _format_from_url(url: str) -> str | None:
    """Guess image format from URL extension or query."""
    path = urlparse(url).path.lower()
    for ext in ("avif", "webp", "jpg", "jpeg", "png", "gif", "svg"):
        if path.endswith("." + ext) or f".{ext}?" in url.lower():
            return "jpeg" if ext == "jpg" else ext
    return None


def _extract_images(html: str, base_url: str) -> list[dict]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    out: list[dict] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        out.append({
            "src": urljoin(base_url, src),
            "alt": img.get("alt"),             # None = missing; "" = decorative
            "alt_present": img.get("alt") is not None,
            "width": img.get("width"),
            "height": img.get("height"),
            "loading": (img.get("loading") or "").lower() or None,
            "fetchpriority": (img.get("fetchpriority") or "").lower() or None,
            "srcset": img.get("srcset") or None,
            "from": "img",
        })
    # <picture><source> alternatives
    for source in soup.find_all("source"):
        srcset = source.get("srcset")
        if not srcset:
            continue
        first_src = srcset.split(",")[0].strip().split()[0]
        if first_src and not first_src.startswith("data:"):
            out.append({
                "src": urljoin(base_url, first_src),
                "alt": None, "alt_present": False,  # source has no alt
                "width": None, "height": None,
                "loading": None, "fetchpriority": None,
                "srcset": srcset,
                "from": "source",
            })
    # CSS background-image (basic regex pass; misses external CSS files)
    for style_attr in re.finditer(
        r'background(?:-image)?\s*:\s*url\(["\']?([^"\')]+)["\']?\)',
        html, re.IGNORECASE,
    ):
        url = style_attr.group(1)
        if url.startswith("data:"):
            continue
        out.append({
            "src": urljoin(base_url, url),
            "alt": None, "alt_present": False,
            "width": None, "height": None,
            "loading": None, "fetchpriority": None,
            "srcset": None,
            "from": "css-background",
        })

    # De-dupe by src preserving order
    seen: set[str] = set()
    dedup: list[dict] = []
    for img in out:
        if img["src"] in seen:
            continue
        seen.add(img["src"])
        dedup.append(img)
    return dedup


def _probe_size(url: str) -> tuple[int | None, str | None]:
    """HEAD probe, return Content-Length if known."""
    try:
        r = requests.head(
            url, timeout=10, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; amazing-seo-skill/images-audit)"},
        )
        cl = r.headers.get("Content-Length")
        return (int(cl) if cl else None, None)
    except (requests.RequestException, ValueError) as e:
        return (None, str(e)[:120])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--max-images", type=int, default=100)
    ap.add_argument("--no-size-probe", action="store_true",
                    help="skip HEAD probe of every image — much faster")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    try:
        r = fetch(args.url, timeout=15)
    except requests.RequestException as e:
        print(json.dumps({"url": args.url, "error": str(e)}, indent=2))
        return 1

    images = _extract_images(r.text, r.url)[:args.max_images]
    for img in images:
        img["format"] = _format_from_url(img["src"])

    # Concurrent size probe
    if not args.no_size_probe and images:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            future_map = {pool.submit(_probe_size, i["src"]): i for i in images}
            for fut in as_completed(future_map):
                img = future_map[fut]
                size, err = fut.result()
                img["bytes"] = size
                img["probe_error"] = err

    # ── Aggregates ──────────────────────────────────────────────────────
    total = len(images)
    if total == 0:
        out = {"url": r.url, "total_images": 0, "issues": []}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    # Alt-text coverage
    missing_alt = [i for i in images if not i["alt_present"] and i["from"] == "img"]
    empty_alt   = [i for i in images if i["alt"] == "" and i["from"] == "img"]
    with_alt    = [i for i in images if i["alt"] and i["from"] == "img"]
    img_count   = sum(1 for i in images if i["from"] == "img")

    # Format mix
    fmt_count: dict[str, int] = {}
    for i in images:
        fmt = i.get("format") or "unknown"
        fmt_count[fmt] = fmt_count.get(fmt, 0) + 1
    next_gen = sum(fmt_count.get(f, 0) for f in ("webp", "avif", "svg"))
    next_gen_pct = round(100 * next_gen / total)

    # Dimensions for CLS prevention (skip CSS-background — dimensions not in HTML)
    needs_dims = [i for i in images if i["from"] in ("img", "source")]
    missing_dims = [i for i in needs_dims if not i["width"] or not i["height"]]

    # Lazy loading: only matters for images other than the first 2-3 (LCP candidates)
    img_only = [i for i in images if i["from"] == "img"]
    below_fold = img_only[3:]   # heuristic: first 3 likely above fold
    not_lazy = [i for i in below_fold if i["loading"] != "lazy"]

    # File size flags
    big = [i for i in images if i.get("bytes") and i["bytes"] >= _SIZE_WARN]
    huge = [i for i in images if i.get("bytes") and i["bytes"] >= _SIZE_CRIT]

    # PNG photographs — heuristic: PNGs > 100KB likely should be JPEG/WebP
    png_photographs = [
        i for i in images
        if i.get("format") == "png" and i.get("bytes") and i["bytes"] > 100 * 1024
    ]

    issues: list[str] = []
    if img_count and len(missing_alt) > 0:
        pct = round(100 * len(missing_alt) / img_count)
        issues.append(f"{len(missing_alt)}/{img_count} <img> tags missing alt attribute ({pct}%) — accessibility + Image Search impact")
    if missing_dims and len(missing_dims) >= 3:
        issues.append(f"{len(missing_dims)} images without width/height — CLS regression risk")
    if huge:
        issues.append(f"{len(huge)} images >= 500KB — LCP regression almost certain")
    if next_gen_pct < _NEXT_GEN_TARGET_PCT:
        issues.append(f"only {next_gen_pct}% next-gen format (WebP/AVIF/SVG); target >= {_NEXT_GEN_TARGET_PCT}%")
    if png_photographs:
        issues.append(f"{len(png_photographs)} large PNGs that look like photos — convert to JPEG/WebP")
    if below_fold and len(not_lazy) > len(below_fold) * 0.5:
        issues.append(f"{len(not_lazy)}/{len(below_fold)} below-fold images missing loading=\"lazy\"")

    out: dict = {
        "url": r.url,
        "total_images": total,
        "image_sources": {
            "img_tag": img_count,
            "source_tag": sum(1 for i in images if i["from"] == "source"),
            "css_background": sum(1 for i in images if i["from"] == "css-background"),
        },
        "alt_coverage": {
            "img_tag_total": img_count,
            "missing_alt_attr": len(missing_alt),
            "empty_alt_decorative": len(empty_alt),
            "has_alt_text": len(with_alt),
            "coverage_pct": round(100 * len(with_alt) / img_count) if img_count else 100,
        },
        "format_mix": fmt_count,
        "next_gen_format_pct": next_gen_pct,
        "dimensions": {
            "needs_dims": len(needs_dims),
            "missing_dims": len(missing_dims),
        },
        "lazy_loading": {
            "below_fold_estimate": len(below_fold),
            "missing_lazy": len(not_lazy),
        },
        "size_findings": {
            "warn_count_200kb": len(big),
            "critical_count_500kb": len(huge),
            "png_photographs": len(png_photographs),
        },
        "samples": {
            "missing_alt": [i["src"] for i in missing_alt[:5]],
            "missing_dims": [i["src"] for i in missing_dims[:5]],
            "huge_images": [{"src": i["src"], "bytes": i["bytes"]} for i in huge[:5]],
            "png_photographs": [{"src": i["src"], "bytes": i["bytes"]} for i in png_photographs[:5]],
        },
        "issues": issues,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

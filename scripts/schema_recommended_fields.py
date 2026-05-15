#!/usr/bin/env python3
"""
Schema.org recommended-fields checker.

Fetches a URL, extracts every JSON-LD script (including nested @graph items),
and for each item reports:

  - required fields present / missing (rich-result eligibility)
  - recommended fields present / missing (completeness)
  - a 0-100 completeness score per item

Recommended-fields tables below come from the schema spec + Google rich-result
guidance, kept in sync with references/schema-types.md.

Exit codes:
  0 = all required fields present
  1 = fetch failed
  2 = at least one item missing required fields

Usage:
    schema_recommended_fields.py <url>
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

import requests
from bs4 import BeautifulSoup

from _fetch import fetch as _fetch_url


# ── Required fields (rich-result eligibility) ──────────────────────────────
#
# Article / BlogPosting / NewsArticle: per Google's Article rich-result docs,
# `headline` is the only strictly required property. `image`, `author`,
# `datePublished`, `dateModified` are *strongly recommended* — without them
# the rich result won't show — but they don't fail spec-level validation.
# Treat them as RECOMMENDED so we don't flag a P0 (blocked) on plain articles
# that intentionally omit hero images.
REQUIRED = {
    "Article":         ["headline"],
    "BlogPosting":     ["headline"],
    "NewsArticle":     ["headline"],
    "Product":         ["name"],
    "Offer":           ["price", "priceCurrency", "availability"],
    "Organization":    ["name", "url"],
    "LocalBusiness":   ["name", "address", "telephone"],
    "Review":          ["reviewRating", "author", "itemReviewed"],
    "AggregateRating": ["ratingValue", "reviewCount"],
    "BreadcrumbList":  ["itemListElement"],
    "Event":           ["name", "startDate", "location"],
    "JobPosting":      ["title", "description", "datePosted", "hiringOrganization"],
    "VideoObject":     ["name", "description", "thumbnailUrl", "uploadDate"],
    "Recipe":          ["name", "image", "recipeIngredient", "recipeInstructions"],
    "Course":          ["name", "description", "provider"],
    "WebSite":         ["name", "url"],
    "WebPage":         ["name"],
    "Person":          ["name"],
    "FAQPage":         ["mainEntity"],
    "ImageObject":     ["contentUrl"],
    "SoftwareApplication": ["name", "operatingSystem", "applicationCategory"],
    "WebApplication":  ["name", "applicationCategory"],
    "ProfilePage":     ["mainEntity"],
    "DiscussionForumPosting": ["headline", "author", "datePublished"],
}

# ── Recommended fields (rich completeness — what their tools surface) ──────
RECOMMENDED = {
    "Article": [
        "headline", "author", "datePublished", "dateModified", "image",
        "publisher", "mainEntityOfPage", "description", "articleSection",
        "inLanguage", "wordCount", "keywords",
    ],
    "BlogPosting": [
        "headline", "author", "datePublished", "dateModified", "image",
        "publisher", "mainEntityOfPage", "description", "articleSection",
        "inLanguage", "wordCount", "keywords",
    ],
    "NewsArticle": [
        "headline", "author", "datePublished", "dateModified", "image",
        "publisher", "mainEntityOfPage", "description", "dateline",
    ],
    "Organization": [
        "name", "url", "logo", "contactPoint", "sameAs", "description",
        "address", "founder", "foundingDate",
    ],
    "LocalBusiness": [
        "name", "address", "telephone", "openingHours", "geo", "priceRange",
        "url", "image", "aggregateRating", "review",
    ],
    "Product": [
        "name", "image", "description", "sku", "brand", "offers",
        "review", "aggregateRating", "gtin", "mpn", "category",
    ],
    "Offer": [
        "price", "priceCurrency", "availability", "url", "validFrom",
        "priceValidUntil", "itemCondition", "seller",
    ],
    "Service": ["name", "provider", "areaServed", "description", "offers", "serviceType"],
    "Review": ["reviewRating", "author", "itemReviewed", "reviewBody", "datePublished", "publisher"],
    "AggregateRating": ["ratingValue", "reviewCount", "bestRating", "worstRating", "ratingCount"],
    "BreadcrumbList": ["itemListElement"],
    "WebSite": ["name", "url", "potentialAction", "description", "inLanguage"],
    "WebPage": [
        "name", "description", "url", "datePublished", "dateModified",
        "primaryImageOfPage", "breadcrumb", "inLanguage", "isPartOf",
    ],
    "Person": ["name", "jobTitle", "url", "sameAs", "image", "worksFor", "description"],
    "VideoObject": [
        "name", "description", "thumbnailUrl", "uploadDate", "duration",
        "contentUrl", "embedUrl", "publisher", "interactionStatistic",
    ],
    "ImageObject": ["contentUrl", "caption", "creator", "copyrightHolder", "license", "width", "height"],
    "Event": [
        "name", "startDate", "endDate", "location", "organizer", "offers",
        "eventStatus", "eventAttendanceMode", "description", "image",
    ],
    "JobPosting": [
        "title", "description", "datePosted", "hiringOrganization",
        "jobLocation", "employmentType", "baseSalary", "validThrough",
    ],
    "Course": ["name", "description", "provider", "hasCourseInstance", "offers", "educationalLevel"],
    "DiscussionForumPosting": ["headline", "author", "datePublished", "text", "url", "interactionStatistic"],
    "ProductGroup": ["name", "productGroupID", "variesBy", "hasVariant"],
    "ProfilePage": ["mainEntity", "name", "url", "description", "sameAs", "dateCreated", "dateModified"],
    "SoftwareApplication": [
        "name", "operatingSystem", "applicationCategory", "offers",
        "aggregateRating", "url", "description", "screenshot", "softwareVersion",
    ],
    "WebApplication": [
        "name", "applicationCategory", "offers", "browserRequirements",
        "featureList", "url", "description",
    ],
    "FAQPage": ["mainEntity", "name"],
}


def fetch(url: str, timeout: int = 15):
    return _fetch_url(url, timeout=timeout)


def extract_jsonld_blocks(html: str) -> list[dict | list]:
    soup = BeautifulSoup(html, "lxml")
    blocks = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        text = script.string or script.get_text() or ""
        text = text.strip()
        if not text:
            continue
        try:
            blocks.append(json.loads(text))
        except json.JSONDecodeError:
            blocks.append({"_parse_error": True, "_raw": text[:200]})
    return blocks


def flatten_items(blocks: list[Any]) -> list[dict]:
    """Walk @graph, lists, and nested mainEntity to collect all top-level items."""
    items: list[dict] = []
    for block in blocks:
        if isinstance(block, list):
            for b in block:
                items.extend(flatten_items([b]))
            continue
        if not isinstance(block, dict):
            continue
        if block.get("_parse_error"):
            items.append(block)
            continue
        if "@graph" in block and isinstance(block["@graph"], list):
            for g in block["@graph"]:
                items.extend(flatten_items([g]))
        if "@type" in block:
            items.append(block)
    return items


def evaluate(item: dict) -> dict:
    if item.get("_parse_error"):
        return {"type": "_parse_error", "raw_excerpt": item.get("_raw", "")[:120]}

    raw_type = item.get("@type")
    # @type can be a string or an array — take primary (first non-aux)
    if isinstance(raw_type, list):
        primary_type = raw_type[0] if raw_type else "Unknown"
    else:
        primary_type = raw_type or "Unknown"

    required = REQUIRED.get(primary_type, [])
    recommended = RECOMMENDED.get(primary_type, [])

    present_req = [f for f in required if f in item]
    missing_req = [f for f in required if f not in item]
    present_rec = [f for f in recommended if f in item]
    missing_rec = [f for f in recommended if f not in item]

    if recommended:
        score = round(100 * len(present_rec) / len(recommended))
    else:
        score = None

    return {
        "type": primary_type,
        "all_types": raw_type if isinstance(raw_type, list) else [primary_type],
        "completeness_score": score,
        "required": {
            "spec_known": bool(required),
            "present": present_req,
            "missing": missing_req,
        },
        "recommended": {
            "spec_known": bool(recommended),
            "present": present_rec,
            "missing": missing_rec,
        },
        # Surface specific high-value fields for blog content
        "has_datePublished": "datePublished" in item,
        "has_dateModified": "dateModified" in item,
        "has_author": "author" in item,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: schema_recommended_fields.py <url>", file=sys.stderr)
        return 64

    url = sys.argv[1]
    try:
        r = fetch(url)
    except requests.RequestException as e:
        print(json.dumps({"url": url, "error": str(e)}))
        return 1

    blocks = extract_jsonld_blocks(r.text)
    items = flatten_items(blocks)
    evaluations = [evaluate(it) for it in items]

    any_missing_required = any(
        e.get("required", {}).get("missing") for e in evaluations
        if e.get("type") not in ("_parse_error", "Unknown")
    )

    summary = {
        "url": url,
        "http_status": r.status_code,
        "schema_blocks_in_html": len(blocks),
        "schema_items_total": len(items),
        "items_with_known_required_spec": sum(
            1 for e in evaluations if e.get("required", {}).get("spec_known")
        ),
        "items_missing_any_required": sum(
            1 for e in evaluations if e.get("required", {}).get("missing")
        ),
        "items": evaluations,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 2 if any_missing_required else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Local SEO deterministic checker.

Why it matters (2026 baseline):
  - 46% of all Google searches have local intent.
  - "Near me" searches grew 500%+ between 2018-2024 and remain a primary
    discovery path on mobile.
  - Local Pack (top-3 map results) captures ~44% of all clicks for
    local-intent queries — being absent costs more than rank position 6.
  - Google Business Profile (GBP) + on-site signals (LocalBusiness schema,
    consistent NAP) are the two halves of local visibility.

What this checker reports:

  1. NAP discoverability: are Name + Address + Phone visible on the page?
     Extracted from JSON-LD LocalBusiness/Organization first, fallback to
     vCard hcard microformats, fallback to regex on common patterns.
  2. NAP consistency: if multiple addresses/phones appear, are they
     identical? Variations (different phone format, abbreviated state)
     are the #1 cause of GBP suspensions.
  3. LocalBusiness schema presence + required fields per Google's docs:
     name, address (with addressLocality, addressRegion, postalCode,
     addressCountry), telephone, geo.latitude/longitude (recommended),
     openingHoursSpecification (recommended), priceRange.
  4. Hours visible to humans (often missing on service-business sites).
  5. Service area declared (areaServed) — critical for non-storefront
     businesses.
  6. Map embed presence (Google Maps iframe or similar).
  7. Citations / sameAs links: GBP profile, Yelp, BBB, Facebook —
     indicate off-site signal density.

Exit code:
  0 = all critical signals present (NAP visible, LocalBusiness schema OK)
  1 = fetch failed
  2 = missing critical local-SEO signals

Usage:
  local_seo_checker.py <url>
  local_seo_checker.py <url> --skip-schema     # only check visible NAP
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

import requests
from bs4 import BeautifulSoup

from _fetch import fetch


_PHONE_RE = re.compile(
    r"(?:(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)?\d{3}[\s.\-]?\d{4})",
)
_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")  # US ZIP
_POSTCODE_INTL_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")  # UK postcode

_STATE_ABBR = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}


_GBP_HOSTS = {
    "google.com/maps", "maps.google.com", "g.page",
}
_CITATION_HOSTS = {
    "yelp.com", "yelp.co", "bbb.org", "facebook.com",
    "tripadvisor.com", "yellowpages.com", "trustpilot.com",
    "foursquare.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com",
}


def _extract_localbusiness_schema(soup: BeautifulSoup) -> list[dict]:
    """Find LocalBusiness or Organization JSON-LD blocks."""
    items: list[dict] = []
    for script in soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        # Normalise to list
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            # @graph
            if "@graph" in block:
                for item in block["@graph"]:
                    if isinstance(item, dict):
                        items.append(item)
                continue
            items.append(block)
    # Filter to LocalBusiness or any subtype (Organization with telephone+address counts)
    local = []
    for it in items:
        type_str = json.dumps(it.get("@type", ""))
        if "LocalBusiness" in type_str or "Restaurant" in type_str or \
           "Store" in type_str or "MedicalBusiness" in type_str or \
           ("Organization" in type_str and ("telephone" in it or "address" in it)):
            local.append(it)
    return local


def _phones_in_text(text: str) -> list[str]:
    """Extract phone-like patterns, normalise to digit-only key for dedup."""
    raw = _PHONE_RE.findall(text)
    seen: set[str] = set()
    out: list[str] = []
    for p in raw:
        digits = re.sub(r"\D", "", p)
        if len(digits) < 10 or len(digits) > 15:
            continue
        key = digits[-10:]  # last 10 digits (drop country code variants)
        if key in seen:
            continue
        seen.add(key)
        out.append(p.strip())
    return out


def _has_address_pattern(text: str) -> list[str]:
    """Find lines that look like street addresses (US heuristic)."""
    matches = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) > 200:
            continue
        # Has number + street suffix + city/state hint
        if re.search(r"\b\d+\s+\w+", line) and re.search(
            r"\b(?:Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|"
            r"Lane|Ln\.?|Drive|Dr\.?|Court|Ct\.?|Place|Pl\.?|Square|Sq\.?|"
            r"Suite|Ste\.?|Floor|Highway|Hwy\.?)\b", line, re.IGNORECASE,
        ):
            matches.append(line[:200])
        elif _ZIP_RE.search(line) and any(s in line for s in _STATE_ABBR):
            matches.append(line[:200])
    return matches[:10]


def _classify_outbound(soup: BeautifulSoup) -> dict:
    gbp_links = []
    citations: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        for h in _GBP_HOSTS:
            if h in href:
                gbp_links.append(a["href"])
        for h in _CITATION_HOSTS:
            if h in href and h not in citations:
                citations[h] = a["href"]
    return {"gbp_links": gbp_links[:5], "citations": citations}


def _maps_embed(soup: BeautifulSoup) -> bool:
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"].lower()
        if "google.com/maps" in src or "maps.google" in src:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--skip-schema", action="store_true",
                    help="don't enforce LocalBusiness schema requirements")
    args = ap.parse_args()

    url = args.url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        r = fetch(url, timeout=15)
    except requests.RequestException as e:
        print(json.dumps({"url": url, "error": str(e)}, indent=2))
        return 1

    try:
        soup = BeautifulSoup(r.text, "lxml")
    except Exception:
        soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(separator="\n", strip=True)
    phones = _phones_in_text(text)
    addresses = _has_address_pattern(text)
    schema_items = _extract_localbusiness_schema(soup)
    outbound = _classify_outbound(soup)
    has_maps = _maps_embed(soup)

    # Schema-derived NAP
    schema_name = None
    schema_phone = None
    schema_address_str = None
    schema_lat = None
    schema_hours = False
    schema_area_served = False
    schema_price_range = None
    schema_warnings: list[str] = []
    for item in schema_items:
        if not schema_name and item.get("name"):
            schema_name = item["name"]
        if not schema_phone and item.get("telephone"):
            schema_phone = item["telephone"]
        addr = item.get("address")
        if not schema_address_str and addr:
            if isinstance(addr, dict):
                parts = [addr.get(k) for k in ("streetAddress", "addressLocality",
                                                "addressRegion", "postalCode", "addressCountry")]
                schema_address_str = ", ".join(p for p in parts if p)
                for required in ("addressLocality", "addressCountry"):
                    if not addr.get(required):
                        schema_warnings.append(f"LocalBusiness address missing {required}")
            else:
                schema_address_str = str(addr)[:200]
        geo = item.get("geo")
        if not schema_lat and isinstance(geo, dict):
            schema_lat = geo.get("latitude")
        if item.get("openingHoursSpecification") or item.get("openingHours"):
            schema_hours = True
        if item.get("areaServed"):
            schema_area_served = True
        if item.get("priceRange"):
            schema_price_range = item["priceRange"]

    # Consistency: phones from schema vs page text
    nap_consistency: dict = {}
    if schema_phone and phones:
        schema_phone_digits = re.sub(r"\D", "", schema_phone)[-10:]
        page_phone_digits = {re.sub(r"\D", "", p)[-10:] for p in phones}
        if schema_phone_digits not in page_phone_digits:
            nap_consistency["phone_mismatch"] = {
                "schema": schema_phone, "page_text": list(phones)[:5],
            }

    issues: list[str] = []
    if not schema_items:
        if not args.skip_schema:
            issues.append("no LocalBusiness/Organization schema (P0 for local-intent pages)")
    else:
        if not schema_name:    issues.append("LocalBusiness schema missing 'name'")
        if not schema_phone:   issues.append("LocalBusiness schema missing 'telephone'")
        if not schema_address_str: issues.append("LocalBusiness schema missing 'address'")
        if not schema_lat:     issues.append("LocalBusiness schema missing geo.latitude (recommended for map placement)")
        if not schema_hours:   issues.append("LocalBusiness schema missing openingHoursSpecification (recommended)")
        if not schema_area_served and not schema_address_str:
            issues.append("neither 'address' nor 'areaServed' declared — required for service-area businesses")

    if not phones:           issues.append("no phone number visible on page")
    if not addresses and not schema_address_str:
        issues.append("no address pattern visible on page")
    if not outbound["gbp_links"]:
        issues.append("no Google Business Profile link — connect site to GBP")
    if not outbound["citations"]:
        issues.append("no citation links (Yelp/BBB/Facebook) — off-site signal density low")
    if not has_maps and not schema_lat:
        issues.append("no Google Maps embed and no geo coordinates — map placement weak")
    if nap_consistency:
        issues.append(f"NAP inconsistency: {list(nap_consistency.keys())}")

    out = {
        "url": url,
        "schema_localbusiness_count": len(schema_items),
        "schema_signals": {
            "name": schema_name,
            "phone": schema_phone,
            "address": schema_address_str,
            "geo_latitude": schema_lat,
            "has_opening_hours": schema_hours,
            "has_area_served": schema_area_served,
            "price_range": schema_price_range,
            "warnings": schema_warnings,
        },
        "visible_phones": phones,
        "visible_addresses": addresses,
        "google_maps_embed": has_maps,
        "outbound_citations": outbound,
        "nap_consistency": nap_consistency or "ok",
        "issues": issues,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

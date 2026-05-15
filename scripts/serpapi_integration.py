#!/usr/bin/env python3
"""
SerpAPI integration — live SERP data for a query.

Why it matters:
  - Google SERPs are increasingly feature-rich: AI Overviews, People Also
    Ask, Featured Snippets, Knowledge Panels, Local Pack, Shopping. Each
    feature changes the CTR distribution dramatically.
  - For competitive analysis, knowing which domains hold top-10 organic
    positions + which SERP features they own is the starting point.
  - SerpAPI normalizes scraping; without it, you're at the mercy of
    Google's rate limits and rendering complexity.

This script is an *optional* layer (L3-equivalent). It activates only
when a SerpAPI key is found in env or Keychain.

What it reports per query:
  - Top-10 organic results: position, URL, title, snippet, domain
  - SERP feature presence: AI Overview, Featured Snippet, People Also Ask,
    Knowledge Panel, Local Pack, Sitelinks, Video Carousel, Image Pack
  - Domain rank for a target domain (if provided): position + URL +
    cited-in-features flags
  - Related questions (PAA) — useful for content gap analysis

API key resolution:
  1. env `SERPAPI_KEY` or `SERPAPI_API_KEY`
  2. macOS Keychain entry `serpapi-key`
  Exits with code 1 if no key found.

Exit code:
  0 = query ran successfully, target domain in top 10 (if provided)
  1 = API/network failure or no key
  2 = target domain not in top 10

Usage:
  serpapi_integration.py "best email marketing tool"
  serpapi_integration.py "best email marketing tool" --target-domain mailchimp.com
  serpapi_integration.py "best email marketing tool" --location "United States" --gl us --hl en
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from urllib.parse import urlparse

import requests


_API_URL = "https://serpapi.com/search.json"


def _resolve_key() -> str | None:
    for name in ("SERPAPI_KEY", "SERPAPI_API_KEY"):
        if k := os.environ.get(name):
            return k.strip()
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", "serpapi-key", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _detect_features(payload: dict) -> dict:
    feats: dict = {}
    feats["ai_overview"] = bool(payload.get("ai_overview"))
    feats["featured_snippet"] = bool(payload.get("answer_box"))
    feats["people_also_ask"] = bool(payload.get("related_questions"))
    feats["knowledge_graph"] = bool(payload.get("knowledge_graph"))
    feats["local_pack"] = bool(payload.get("local_results"))
    feats["shopping"] = bool(payload.get("shopping_results"))
    feats["images"] = bool(payload.get("inline_images"))
    feats["videos"] = bool(payload.get("inline_videos"))
    feats["news"] = bool(payload.get("top_stories"))
    feats["sitelinks_searchbox"] = any(
        r.get("sitelinks", {}).get("inline")
        for r in payload.get("organic_results", [])
    )
    return feats


def _target_domain_match(host: str, target: str) -> bool:
    host = (host or "").lower().lstrip(".")
    target = target.lower().lstrip(".")
    if target.startswith("www."):
        target = target[4:]
    return host == target or host.endswith("." + target) or host == "www." + target


def _organic_top10(payload: dict) -> list[dict]:
    out = []
    for r in (payload.get("organic_results") or [])[:10]:
        link = r.get("link", "")
        out.append({
            "position": r.get("position"),
            "title": r.get("title"),
            "url": link,
            "domain": urlparse(link).netloc,
            "snippet": (r.get("snippet") or "")[:200],
            "has_sitelinks": bool(r.get("sitelinks")),
            "has_rich_snippet": bool(r.get("rich_snippet")),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("query")
    ap.add_argument("--target-domain", default=None,
                    help="domain to highlight in results (returns rank + features)")
    ap.add_argument("--location", default=None,
                    help="city / country e.g. 'New York, NY' or 'United Kingdom'")
    ap.add_argument("--gl", default="us", help="country code for Google (default us)")
    ap.add_argument("--hl", default="en", help="language code for Google (default en)")
    ap.add_argument("--device", choices=["desktop", "mobile", "tablet"], default="desktop")
    args = ap.parse_args()

    key = _resolve_key()
    if not key:
        print(json.dumps({
            "error": "no SerpAPI key found. Set SERPAPI_KEY env var or Keychain `serpapi-key`. "
                     "Get a key (free 100 searches/mo): https://serpapi.com/users/sign_up",
        }, indent=2), file=sys.stderr)
        return 1

    params = {
        "q": args.query, "api_key": key, "engine": "google",
        "gl": args.gl, "hl": args.hl, "device": args.device,
    }
    if args.location:
        params["location"] = args.location

    try:
        r = requests.get(_API_URL, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
    except requests.RequestException as e:
        print(json.dumps({"error": f"SerpAPI request failed: {e}"}, indent=2))
        return 1

    if payload.get("error"):
        print(json.dumps({"error": f"SerpAPI: {payload['error']}"}, indent=2))
        return 1

    top10 = _organic_top10(payload)
    features = _detect_features(payload)
    paa = [q.get("question") for q in (payload.get("related_questions") or [])[:10]]

    target_position = None
    target_in_ai_overview = False
    target_in_paa = False
    if args.target_domain:
        for r in top10:
            if _target_domain_match(r["domain"], args.target_domain):
                target_position = r["position"]
                break
        # AI Overview citation check
        if features["ai_overview"]:
            for src in (payload.get("ai_overview") or {}).get("sources", []) or []:
                if _target_domain_match(urlparse(src.get("link", "")).netloc, args.target_domain):
                    target_in_ai_overview = True
                    break

    out = {
        "query": args.query,
        "location": args.location, "gl": args.gl, "hl": args.hl, "device": args.device,
        "serp_features": features,
        "feature_count": sum(1 for v in features.values() if v),
        "top10": top10,
        "people_also_ask": paa,
        "target_analysis": {
            "domain": args.target_domain,
            "organic_position": target_position,
            "in_top10": target_position is not None,
            "cited_in_ai_overview": target_in_ai_overview,
        } if args.target_domain else None,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))

    if args.target_domain and target_position is None:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
AEO citation probe via Google Gemini + Google Search grounding.

Closes the Google AI Overviews / AI Mode gap in the 4-LLM ensemble. Sends each
query to Gemini with `google_search` grounding enabled, then inspects the
returned `groundingMetadata.groundingChunks` to see if the target domain
appears among the cited web sources. This is the closest publicly-available
proxy for "would Google AI Overviews cite this domain for this query?" —
both surfaces use the same underlying Google Search index and Gemini ranking.

API key resolution (in order):
  1. env var GOOGLE_GEMINI_API_KEY
  2. macOS Keychain entry `google-gemini-api-key`
  3. (fallback) GOOGLE_AI_STUDIO_API_KEY env var
  Exits with code 1 if no key is found.

Usage:
  aeo_gemini.py <domain> "<query1>" ["<query2>" ...] [--model gemini-2.5-flash] [--json]

Examples:
  aeo_gemini.py example.com "best email marketing tool" "alternatives to mailchimp"
  aeo_gemini.py example.com "what is RAG" --model gemini-2.5-pro --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Iterable
from urllib.parse import urlparse

import requests


_DEFAULT_MODEL = "gemini-2.5-flash"
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _resolve_api_key() -> str | None:
    for env_name in ("GOOGLE_GEMINI_API_KEY", "GOOGLE_AI_STUDIO_API_KEY"):
        if k := os.environ.get(env_name):
            return k.strip()
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "google-gemini-api-key", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _domain_in_url(domain: str, url: str) -> bool:
    """Match domain against URL's hostname, accepting subdomains and apex variants."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower().lstrip(".")
    target = domain.lower().lstrip(".")
    if target.startswith("www."):
        target = target[4:]
    return host == target or host.endswith("." + target) or host == "www." + target


def _extract_citations(response: dict) -> list[dict]:
    """Pull grounding chunks (web sources Gemini used) from a Gemini response."""
    out: list[dict] = []
    for cand in response.get("candidates", []):
        gm = cand.get("groundingMetadata") or {}
        for chunk in gm.get("groundingChunks", []):
            web = chunk.get("web") or {}
            uri = web.get("uri")
            title = web.get("title")
            if uri:
                out.append({"uri": uri, "title": title})
    # Dedupe preserving order
    seen: set[str] = set()
    dedup: list[dict] = []
    for c in out:
        if c["uri"] in seen:
            continue
        seen.add(c["uri"])
        dedup.append(c)
    return dedup


def _query_gemini(api_key: str, model: str, query: str, timeout: int = 60) -> dict:
    # Direct requests.post — exempt from _fetch wrapping because:
    #   (a) fixed Google API endpoint, no SSRF surface
    #   (b) _fetch.fetch is GET-only
    # Retry on 5xx (transient Gemini outages happen).
    import time
    url = _ENDPOINT.format(model=model)
    body = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    for attempt in range(3):
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
        if r.status_code >= 500 and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


def _answer_text(response: dict) -> str:
    for cand in response.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if "text" in part:
                return part["text"]
    return ""


def probe(domain: str, queries: Iterable[str], api_key: str, model: str) -> dict:
    results: list[dict] = []
    for q in queries:
        try:
            resp = _query_gemini(api_key, model, q)
        except requests.HTTPError as e:
            body = e.response.text[:300] if e.response is not None else ""
            results.append({
                "query": q, "error": f"HTTP {e.response.status_code if e.response else '?'}: {body}",
            })
            continue
        except requests.RequestException as e:
            results.append({"query": q, "error": str(e)})
            continue

        citations = _extract_citations(resp)
        cited = any(_domain_in_url(domain, c["uri"]) for c in citations)
        results.append({
            "query": q,
            "cited": cited,
            "citation_count": len(citations),
            "citations": citations[:20],
            "answer_excerpt": _answer_text(resp)[:300],
        })

    cited_queries = [r for r in results if r.get("cited")]
    return {
        "domain": domain,
        "provider": "gemini",
        "model": model,
        "queries_total": len(results),
        "queries_cited": len(cited_queries),
        "citation_rate": (len(cited_queries) / len(results)) if results else 0,
        "per_query": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("domain")
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--model", default=_DEFAULT_MODEL,
                    help="gemini-2.5-flash (default) or gemini-2.5-pro")
    ap.add_argument("--json", action="store_true",
                    help="output raw JSON instead of human summary")
    args = ap.parse_args()

    api_key = _resolve_api_key()
    if not api_key:
        print("ERROR: Gemini API key not found. Set GOOGLE_GEMINI_API_KEY or "
              "add Keychain item `google-gemini-api-key`:", file=sys.stderr)
        print("  security add-generic-password -s google-gemini-api-key -a $USER -w", file=sys.stderr)
        return 1

    result = probe(args.domain, args.queries, api_key, args.model)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Gemini ({args.model}) — citation probe for {args.domain}")
        print(f"  queries: {result['queries_total']}, cited: {result['queries_cited']} "
              f"({result['citation_rate']*100:.0f}%)")
        for r in result["per_query"]:
            marker = "✓" if r.get("cited") else "✗"
            if "error" in r:
                marker = "!"
            print(f"  {marker} {r['query'][:80]}")
            if "error" in r:
                print(f"     error: {r['error'][:150]}")
                continue
            if r.get("cited"):
                for c in r["citations"]:
                    hit = "←" if _domain_in_url(args.domain, c["uri"]) else " "
                    print(f"     {hit} {c['uri'][:90]}")

    return 0 if result["queries_cited"] > 0 else 2


if __name__ == "__main__":
    sys.exit(main())

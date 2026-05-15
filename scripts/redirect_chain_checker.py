#!/usr/bin/env python3
"""
Redirect chain + canonical alignment deterministic checker.

Given a URL, follows redirects step-by-step (manually, not via requests'
automatic redirect handling so we can inspect each hop) and reports:

  - the full chain: status / Location / hop count
  - whether HTTP → HTTPS upgrade happens, and where
  - 301 vs 302 vs 307/308 distribution (302 for permanent moves is a smell)
  - whether the final URL's canonical tag aligns with the resolved URL
  - whether canonical and final URL agree on protocol, host, and trailing slash
  - cycle / loop detection (already-seen URL revisited)

Exit code:
  0 = single hop or clean short chain, canonical aligns
  1 = fetch failed
  2 = problems found (long chain, 302 for permanent move, canonical mismatch,
       protocol drift, loop)

Usage:
  redirect_chain_checker.py <url> [--max-hops N]
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from _fetch import _check_ssrf, _DEFAULT_UA, _BASE_HEADERS


_DEFAULT_MAX_HOPS = 10


def _follow(url: str, max_hops: int) -> dict:
    """Walk redirects manually, recording each hop."""
    chain: list[dict] = []
    seen: set[str] = set()
    current = url

    headers = dict(_BASE_HEADERS)
    headers["User-Agent"] = _DEFAULT_UA

    for hop in range(max_hops + 1):
        _check_ssrf(current)
        if current in seen:
            chain.append({"url": current, "status": None, "error": "loop detected"})
            return {"chain": chain, "final_url": None, "loop": True}
        seen.add(current)

        try:
            r = requests.get(current, headers=headers, timeout=15,
                             allow_redirects=False)
        except requests.RequestException as e:
            chain.append({"url": current, "status": None, "error": str(e)})
            return {"chain": chain, "final_url": None, "fetch_error": True}

        entry = {
            "url": current,
            "status": r.status_code,
            "location": r.headers.get("Location"),
        }
        chain.append(entry)

        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location")
            if not loc:
                entry["error"] = f"{r.status_code} without Location header"
                return {"chain": chain, "final_url": None}
            current = urljoin(current, loc)
            continue

        return {"chain": chain, "final_url": current, "final_body": r.text,
                "final_headers": dict(r.headers)}

    chain.append({"warning": f"max_hops ({max_hops}) exceeded"})
    return {"chain": chain, "final_url": None, "max_hops_exceeded": True}


def _extract_canonical(html: str, base_url: str) -> str | None:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        return urljoin(base_url, link["href"])
    return None


def _norm(url: str) -> str:
    """Lowercase host, strip default port, normalise trailing slash for compare."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    port = p.port
    netloc = host if not port or port in (80, 443) else f"{host}:{port}"
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{p.scheme}://{netloc}{path}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url")
    ap.add_argument("--max-hops", type=int, default=_DEFAULT_MAX_HOPS)
    args = ap.parse_args()

    result = _follow(args.url, args.max_hops)
    chain = result["chain"]
    out: dict = {
        "input_url": args.url,
        "hop_count": max(0, len(chain) - 1),
        "chain": chain,
        "final_url": result.get("final_url"),
        "issues": [],
    }

    if result.get("loop"):
        out["issues"].append("redirect loop detected")
    if result.get("max_hops_exceeded"):
        out["issues"].append(f"chain longer than {args.max_hops} hops")
    if result.get("fetch_error"):
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 1

    # Status mix analysis (skip the final 2xx and the loop/error sentinels)
    statuses = [h["status"] for h in chain if h.get("status")]
    out["status_codes"] = statuses
    redirect_statuses = [s for s in statuses if 300 <= s < 400]
    if redirect_statuses:
        out["redirect_types"] = {
            "301_permanent": redirect_statuses.count(301),
            "302_temporary": redirect_statuses.count(302),
            "303_see_other": redirect_statuses.count(303),
            "307_temp_preserve": redirect_statuses.count(307),
            "308_perm_preserve": redirect_statuses.count(308),
        }

    # HTTP → HTTPS upgrade detection
    schemes_in_chain = [urlparse(h["url"]).scheme for h in chain if h.get("url")]
    if "http" in schemes_in_chain and "https" in schemes_in_chain:
        out["http_to_https_upgrade"] = True
    elif schemes_in_chain and schemes_in_chain[0] == "http" and "https" not in schemes_in_chain:
        out["http_only_no_upgrade"] = True
        out["issues"].append("HTTP requested, no upgrade to HTTPS happened")

    # Hop-count rule: each extra hop is link equity / latency cost
    if out["hop_count"] >= 3:
        out["issues"].append(f"redirect chain has {out['hop_count']} hops (recommend ≤1)")
    elif out["hop_count"] >= 2:
        out["issues"].append(f"redirect chain has {out['hop_count']} hops (1 is the ideal)")

    # 302 for content that looks permanent (heuristic: host change)
    for h in chain:
        if h.get("status") == 302 and h.get("location"):
            from_host = urlparse(h["url"]).hostname or ""
            to_host = urlparse(h["location"]).hostname or ""
            if from_host != to_host:
                out["issues"].append(
                    f"302 (temporary) used for host change {from_host} → {to_host}; "
                    "use 301 if permanent"
                )

    # Canonical alignment on the final URL
    if result.get("final_url") and result.get("final_body"):
        canonical = _extract_canonical(result["final_body"], result["final_url"])
        out["canonical"] = canonical
        if canonical:
            if _norm(canonical) != _norm(result["final_url"]):
                out["canonical_mismatch"] = {
                    "canonical": canonical,
                    "final_url": result["final_url"],
                    "canonical_norm": _norm(canonical),
                    "final_norm": _norm(result["final_url"]),
                }
                out["issues"].append(
                    "canonical tag does not match the resolved final URL"
                )
        else:
            out["issues"].append("no canonical tag on final page")

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if out["issues"] else 0


if __name__ == "__main__":
    sys.exit(main())

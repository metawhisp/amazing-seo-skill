#!/usr/bin/env python3
"""
Security headers deterministic checker.

Why it matters for SEO (Page Experience signals, May 2026 baseline):
  - Google's Page Experience update folded user-safety signals into core
    ranking. Sites without proper security headers are flagged in
    Search Console.
  - HTTPS has been a ranking signal since 2014; HSTS demonstrates the
    HTTPS deployment is complete and intentional.
  - Modern audits from Ahrefs / SEMrush surface these headers as standard
    findings: their absence is a P1 issue.
  - Mixed-content warnings actively trigger "Not Secure" badges in Chrome
    that hurt CTR.

What we check on the target URL:

  1. HSTS (Strict-Transport-Security): present, max-age >= 1 year (31536000),
     `includeSubDomains` recommended, `preload` flag noted
  2. Content-Security-Policy (CSP): present, NOT `default-src 'unsafe-inline'`
     or `'unsafe-eval'` without explicit nonce/hash. Report-only also flagged.
  3. X-Frame-Options or CSP frame-ancestors: clickjacking protection
  4. X-Content-Type-Options: must be `nosniff`
  5. Referrer-Policy: present (any sane value; we flag `unsafe-url`)
  6. Permissions-Policy (was Feature-Policy): presence noted
  7. HTTPS: scheme is https, no mixed content in initial HTML
  8. Mixed-content detection: <img|script|link|iframe src/href="http://..."

Exit code:
  0 = all critical headers present and well-formed
  1 = fetch failed
  2 = one or more critical security issues

Usage:
  security_headers_checker.py <url>
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse

import requests

from _fetch import fetch, finding, result_envelope


_HSTS_MIN_MAX_AGE = 31_536_000   # 1 year — Google's strict-transport rec
_MIXED_CONTENT_RE = re.compile(
    r'''(?:src|href)\s*=\s*["']http://[^"']+''', re.IGNORECASE,
)


def _parse_hsts(value: str) -> dict:
    """Parse Strict-Transport-Security header into directives."""
    out: dict = {"raw": value, "max_age": None, "include_subdomains": False, "preload": False}
    for part in value.split(";"):
        part = part.strip()
        if part.lower().startswith("max-age="):
            try:
                out["max_age"] = int(part.split("=", 1)[1])
            except ValueError:
                pass
        elif part.lower() == "includesubdomains":
            out["include_subdomains"] = True
        elif part.lower() == "preload":
            out["preload"] = True
    return out


def _analyze_csp(value: str) -> dict:
    """Surface common CSP weaknesses."""
    raw = value
    parts = {}
    for directive in re.split(r"\s*;\s*", value.strip()):
        if not directive:
            continue
        bits = directive.split()
        if not bits:
            continue
        parts[bits[0].lower()] = bits[1:]

    has_unsafe_inline = any("'unsafe-inline'" in tokens for tokens in parts.values())
    has_unsafe_eval = any("'unsafe-eval'" in tokens for tokens in parts.values())
    has_default_src = "default-src" in parts
    has_frame_ancestors = "frame-ancestors" in parts
    has_nonce_or_hash = any(
        any(t.startswith("'nonce-") or t.startswith("'sha256-") or t.startswith("'sha384-")
            for t in tokens)
        for tokens in parts.values()
    )

    return {
        "raw_truncated": raw[:400] + ("..." if len(raw) > 400 else ""),
        "directive_count": len(parts),
        "has_default_src": has_default_src,
        "has_frame_ancestors": has_frame_ancestors,
        "has_unsafe_inline": has_unsafe_inline,
        "has_unsafe_eval": has_unsafe_eval,
        "uses_nonce_or_hash": has_nonce_or_hash,
    }


def _scan_mixed_content(html: str) -> list[str]:
    """Find http:// resource references in HTML (excluding anchor href)."""
    hits = []
    for match in _MIXED_CONTENT_RE.finditer(html):
        hits.append(match.group(0)[:120])
        if len(hits) >= 20:
            break
    return hits


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: security_headers_checker.py <url>", file=sys.stderr)
        return 64

    url = sys.argv[1]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        r = fetch(url, timeout=15)
    except requests.RequestException as e:
        print(json.dumps({"url": url, "error": str(e)}, indent=2))
        return 1

    headers = {k.lower(): v for k, v in r.headers.items()}
    is_https = urlparse(r.url).scheme == "https"
    payload: dict = {"is_https": is_https}
    issues: list[dict] = []

    # 1. HSTS
    hsts_raw = headers.get("strict-transport-security")
    if not is_https:
        issues.append(finding("P0", "served over HTTP, not HTTPS — Google ranking penalty"))
        payload["hsts"] = None
    elif not hsts_raw:
        issues.append(finding("P1", "missing Strict-Transport-Security header"))
        payload["hsts"] = None
    else:
        h = _parse_hsts(hsts_raw)
        payload["hsts"] = h
        if not h["max_age"] or h["max_age"] < _HSTS_MIN_MAX_AGE:
            issues.append(finding("P1",
                f"HSTS max-age too short ({h['max_age']}s; recommend >= {_HSTS_MIN_MAX_AGE}s)",
                {"current_max_age": h["max_age"], "recommended_min": _HSTS_MIN_MAX_AGE}))
        if not h["include_subdomains"]:
            issues.append(finding("P1",
                "HSTS missing includeSubDomains (recommended unless you have non-HTTPS subdomains)"))

    # 2. CSP
    csp_raw = headers.get("content-security-policy")
    cspro_raw = headers.get("content-security-policy-report-only")
    if not csp_raw and not cspro_raw:
        issues.append(finding("P1", "missing Content-Security-Policy header"))
        payload["csp"] = None
    else:
        primary = csp_raw or cspro_raw
        analysis = _analyze_csp(primary)
        analysis["mode"] = "enforced" if csp_raw else "report-only"
        payload["csp"] = analysis
        if not csp_raw and cspro_raw:
            issues.append(finding("P2",
                "CSP is report-only, not enforced — switch to enforcing mode when ready"))
        if analysis["has_unsafe_inline"] and not analysis["uses_nonce_or_hash"]:
            issues.append(finding("P0",
                "CSP allows 'unsafe-inline' without nonce/hash — defeats XSS protection"))
        if analysis["has_unsafe_eval"]:
            issues.append(finding("P0", "CSP allows 'unsafe-eval' — security weakening"))
        if not analysis["has_default_src"]:
            issues.append(finding("P2",
                "CSP missing default-src — fallback for unspecified resource types"))

    # 3. Clickjacking protection
    xfo = headers.get("x-frame-options")
    csp_has_fa = bool(payload.get("csp") and payload["csp"].get("has_frame_ancestors"))
    payload["x_frame_options"] = xfo
    payload["clickjacking_protected"] = bool(xfo) or csp_has_fa
    if not payload["clickjacking_protected"]:
        issues.append(finding("P1",
            "no clickjacking protection — set X-Frame-Options: DENY or CSP frame-ancestors"))

    # 4. X-Content-Type-Options
    xcto = headers.get("x-content-type-options", "").lower()
    payload["x_content_type_options"] = xcto or None
    if xcto != "nosniff":
        issues.append(finding("P2",
            "X-Content-Type-Options is not 'nosniff' — MIME-sniff attacks possible"))

    # 5. Referrer-Policy
    rp = headers.get("referrer-policy")
    payload["referrer_policy"] = rp
    if not rp:
        issues.append(finding("P2", "missing Referrer-Policy header"))
    elif rp.lower() in ("unsafe-url", "no-referrer-when-downgrade"):
        issues.append(finding("P2",
            f"Referrer-Policy={rp!r} leaks referrer to HTTP origins — consider 'strict-origin-when-cross-origin'"))

    # 6. Permissions-Policy
    pp = headers.get("permissions-policy") or headers.get("feature-policy")
    payload["permissions_policy"] = pp
    if not pp:
        issues.append(finding("P2", "missing Permissions-Policy header (informational)"))

    # 7. Mixed content scan
    mixed = _scan_mixed_content(r.text) if is_https else []
    payload["mixed_content"] = {"count": len(mixed), "samples": mixed[:10]}
    if mixed:
        issues.append(finding("P1",
            f"mixed content: {len(mixed)} http:// resources on HTTPS page",
            {"sample_urls": mixed[:10]}))

    payload["issues"] = issues
    payload["score"] = max(0, 100 - sum(
        {"P0": 15, "P1": 10, "P2": 3}[i["severity"]] for i in issues
    ))
    out = result_envelope(target=url, response=r, checker="security_headers_checker.py", **payload)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

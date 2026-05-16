"""
Shared HTTP fetch helper + JSON envelope for all amazing-seo-skill checkers.

Centralises four concerns every checker has:

  1. **User-Agent.** Defaults to a realistic Chrome UA so checkers don't
     get 403'd by Cloudflare / Akamai / WAFs that block custom bot UAs.
     Override per-call with `ua=` or globally via env `AMAZING_SEO_UA`.

  2. **SSRF guard.** Resolves the hostname and refuses private / loopback /
     link-local / reserved IPs. Skip with `allow_private=True` only when
     the caller intentionally targets local infra.

  3. **Retries + backoff.** Transient 5xx and connection errors get up to
     `max_retries` retries with exponential backoff. 4xx is returned as-is
     (callers want to see 404 / 410 / 451).

  4. **Standardized JSON envelope.** Every checker wraps its output via
     `result_envelope(target, response, checker, **payload)` so downstream
     consumers (page_score, audit_history, dashboard) get the same fields
     in the same place: target, final_url, http_status, generated_at,
     skill_version, checker. Plus standardized `issues: [{severity, text,
     evidence}]` format.

Public surface:
    fetch(url, *, timeout=15, ua=None, headers=None, max_retries=2,
          allow_private=False) -> requests.Response
    SSRFBlocked  — raised when SSRF guard rejects the target
    result_envelope(...) — standardized JSON wrapper
    finding(severity, text, evidence=None) — standardized P0/P1/P2 marker
    SKILL_VERSION — current skill version string
"""
from __future__ import annotations

import ipaddress
import os
import socket
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import requests


SKILL_VERSION = "0.7.0"


_DEFAULT_UA = os.environ.get(
    "AMAZING_SEO_UA",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)

# NOTE on Accept-Encoding: we only advertise encodings `requests` can decode
# natively. Adding `br` here without installing the `brotli` package causes
# servers to send compressed bodies that requests returns as raw bytes — the
# checkers then see garbled "HTML" and report file-malformed errors.
_BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class SSRFBlocked(requests.RequestException):
    """Raised when a target URL resolves to a private / internal address."""


def _check_ssrf(url: str) -> None:
    """Resolve hostname and raise SSRFBlocked for private / internal IPs."""
    host = urlparse(url).hostname
    if not host:
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # DNS failure — let requests surface the real error
        return
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            raise SSRFBlocked(
                f"blocked: {host} resolves to non-public address {ip}"
            )


def fetch(
    url: str,
    *,
    timeout: int = 15,
    ua: Optional[str] = None,
    headers: Optional[dict] = None,
    max_retries: int = 2,
    allow_private: bool = False,
) -> requests.Response:
    """Fetch a URL with realistic UA, SSRF guard, and retries on 5xx/network errors."""
    if not allow_private:
        _check_ssrf(url)

    final_headers = dict(_BASE_HEADERS)
    final_headers["User-Agent"] = ua or _DEFAULT_UA
    if headers:
        final_headers.update(headers)

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(
                url, timeout=timeout, allow_redirects=True, headers=final_headers,
            )
            if 500 <= r.status_code < 600 and attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise

    assert last_exc is not None
    raise last_exc


# ── Standardized JSON envelope ────────────────────────────────────────────
# Every checker emits its top-level dict through this helper so downstream
# tools (page_score, audit_history, dashboard, render_html_report) can rely
# on:
#   - target / final_url / http_status — fields named identically across
#     all checkers (was inconsistent: some had `url`, some `final_url`,
#     some both, some `http_status`, some none)
#   - generated_at / skill_version — for history.db forensics + trend
#     attribution (was missing entirely)
#   - checker — name of the script that produced the result
#   - issues: [{severity, text, evidence}, ...] — severity travels WITH
#     the finding, not regex-classified later (fixes brittle classifier
#     in page_score.py that silently failed on issue-wording changes)

def result_envelope(
    target: str,
    response: requests.Response | None,
    checker: str,
    **payload: Any,
) -> dict:
    """Wrap a checker's output in the standard envelope.

    Args:
        target:    The URL the caller was asked to check (pre-redirect input).
        response:  The requests.Response from a successful fetch, or None
                   if the checker didn't fetch directly (e.g. log_analyzer).
                   We use response.url for final_url and response.status_code
                   for http_status when present.
        checker:   The checker filename (e.g. "robots_checker.py") for
                   provenance in history.
        **payload: All checker-specific fields go here. Must include `issues`
                   (list of dicts with `severity` + `text`) when there are
                   findings.

    Returns:
        Standardized dict ready to json.dumps.
    """
    envelope = {
        "target": target,
        "final_url": response.url if response is not None else None,
        "http_status": response.status_code if response is not None else None,
        "checker": checker,
        "skill_version": SKILL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    envelope.update(payload)
    return envelope


def finding(
    severity: str,
    text: str,
    evidence: Any | None = None,
) -> dict:
    """Construct a standardized finding dict.

    severity: 'P0' (blocks indexing / penalty), 'P1' (significant ranking
              impact), 'P2' (optimization opportunity). See
              references/severity-rubric.md for full criteria.

    text:     Human-readable, prefer specific numbers ("64 missing
              canonicals") over vague ("some canonicals missing").

    evidence: Optional structured data — e.g. {"affected_urls": [...]}.
              Surfaces in dashboard run-detail page for drill-down.
    """
    if severity not in ("P0", "P1", "P2"):
        raise ValueError(f"severity must be P0/P1/P2, got {severity!r}")
    f = {"severity": severity, "text": text}
    if evidence is not None:
        f["evidence"] = evidence
    return f

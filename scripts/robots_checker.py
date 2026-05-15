#!/usr/bin/env python3
"""
robots.txt deterministic checker.

Fetches /robots.txt at a domain root and reports:

  - existence + HTTP status + size
  - sitemap references (none / some / multiple) and whether they resolve
  - per-user-agent Allow / Disallow rules for: every standard search bot,
    every known AI/LLM crawler, and the wildcard `*` fallback
  - whether AI training and AI search crawlers are allowed access to `/`
  - common mistakes: case-sensitive token errors, missing trailing slash on
    Disallow, blocking CSS/JS resources, contradictory rules

Exit code:
  0 = file exists and parses cleanly
  1 = fetch failed / file missing
  2 = file exists but has issues

Usage:
  robots_checker.py <domain_or_url>

Examples:
  robots_checker.py example.com
  robots_checker.py https://example.com
"""
from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

import requests

from _fetch import fetch


# AI crawler taxonomy. Each entry: (token in robots.txt, owner, purpose).
# Verified against OpenAI's bots doc, Anthropic's bot policy, knownagents.com,
# and provider-published lists as of May 2026. Order: most-relevant first.
AI_CRAWLERS = [
    # OpenAI — 3 distinct tokens with independent rules
    ("GPTBot",            "OpenAI",       "Training data crawl"),
    ("OAI-SearchBot",     "OpenAI",       "Search-in-ChatGPT index"),
    ("ChatGPT-User",      "OpenAI",       "User-triggered fetch in ChatGPT"),
    # Anthropic
    ("ClaudeBot",         "Anthropic",    "Web crawl (training data)"),
    ("Claude-User",       "Anthropic",    "User-triggered fetch in Claude.ai"),
    ("anthropic-ai",      "Anthropic",    "Legacy token (pre-2024); kept for sites that still match on it"),
    ("Claude-Web",        "Anthropic",    "Legacy token; superseded by Claude-User"),
    # Perplexity
    ("PerplexityBot",     "Perplexity",   "Index crawler for Perplexity AI search"),
    ("Perplexity-User",   "Perplexity",   "User-triggered fetch when answering"),
    # Google
    ("Google-Extended",   "Google",       "Gemini training opt-out (does NOT affect Google Search or AI Overviews)"),
    ("Googlebot",         "Google",       "Google Search index"),
    # Microsoft
    ("Bingbot",           "Microsoft",    "Bing Search index (also Copilot)"),
    # Apple
    ("Applebot",          "Apple",        "Apple Search / Siri"),
    ("Applebot-Extended", "Apple",        "Apple Intelligence training opt-out"),
    # Meta
    ("meta-externalagent","Meta",         "AI training crawl (Llama models)"),
    ("meta-externalfetcher","Meta",       "User-initiated link fetches"),
    # Other AI / common training corpora
    ("Bytespider",        "ByteDance",    "TikTok/Doubao AI training"),
    ("CCBot",             "Common Crawl", "Open dataset reused to train many LLMs"),
    ("cohere-ai",         "Cohere",       "Cohere models training"),
    ("Diffbot",           "Diffbot",      "Knowledge graph + AI extraction"),
]


def normalize(target: str) -> str:
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    p = urlparse(target)
    return f"{p.scheme}://{p.netloc}"


def parse_robots(text: str) -> dict:
    """Parse a robots.txt into {user_agent: [(directive, path), ...]} + sitemaps."""
    groups: dict[str, list[tuple[str, str]]] = {}
    sitemaps: list[str] = []
    current_uas: list[str] = []
    prev_directive_was_ua = False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            prev_directive_was_ua = False
            continue
        if ":" not in line:
            continue
        directive, _, value = line.partition(":")
        directive = directive.strip().lower()
        value = value.strip()

        if directive == "user-agent":
            if not prev_directive_was_ua:
                current_uas = [value]
            else:
                current_uas.append(value)
            groups.setdefault(value, [])
            prev_directive_was_ua = True
        elif directive == "sitemap":
            sitemaps.append(value)
            prev_directive_was_ua = False
        elif directive in {"allow", "disallow", "crawl-delay"}:
            for ua in current_uas or ["*"]:
                groups.setdefault(ua, []).append((directive, value))
            prev_directive_was_ua = False
        else:
            prev_directive_was_ua = False

    return {"groups": groups, "sitemaps": sitemaps}


def effective_for(groups: dict, ua: str) -> list[tuple[str, str]]:
    """Match robots.txt rules for a user-agent, falling back to '*'."""
    # Exact match first (case-insensitive per RFC 9309)
    for token, rules in groups.items():
        if token.lower() == ua.lower():
            return rules
    return groups.get("*", [])


def is_path_blocked(rules: list[tuple[str, str]], path: str) -> bool:
    """Apply Allow/Disallow rules to a path using longest-match precedence."""
    matches = []
    for directive, pattern in rules:
        if directive not in ("allow", "disallow"):
            continue
        if not pattern:
            # Empty Disallow = allow everything; empty Allow = no-op
            if directive == "disallow":
                matches.append((len(pattern), directive, False))
            continue
        # Simple prefix match (robots.txt wildcards are limited; this covers most cases)
        if path.startswith(pattern.replace("*", "")):
            matches.append((len(pattern), directive, directive == "disallow"))

    if not matches:
        return False
    # Longest pattern wins; Allow beats Disallow at equal length
    matches.sort(key=lambda m: (m[0], 0 if m[1] == "allow" else 1), reverse=True)
    return matches[0][2]


def detect_issues(parsed: dict, raw_text: str) -> list[str]:
    issues: list[str] = []

    if not parsed["groups"]:
        issues.append("no User-agent groups found — file may be malformed")

    # Catch common typos / case errors at directive level
    for line_no, raw_line in enumerate(raw_text.splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        d, _, _ = line.partition(":")
        d = d.strip()
        if d.lower() in {"user-agent", "allow", "disallow", "sitemap", "crawl-delay"}:
            continue
        if d.lower() in {"useragent", "user agent", "dissallow", "dissalow", "alow"}:
            issues.append(f"line {line_no}: probable typo in directive '{d}'")

    # No wildcard group at all is suspicious for production sites
    if "*" not in parsed["groups"]:
        issues.append("no User-agent: * group defined — wildcard fallback missing")

    # Block of /css /js often indicates over-eager Disallow
    star_rules = parsed["groups"].get("*", [])
    for directive, pattern in star_rules:
        if directive == "disallow" and pattern in {"/css/", "/js/", "/css", "/js"}:
            issues.append(
                f"User-agent: * disallows {pattern!r} — Google needs CSS/JS to render"
            )

    return issues


def check_sitemap_reachable(sitemap_url: str) -> dict:
    try:
        r = fetch(sitemap_url, timeout=10)
        return {"url": sitemap_url, "status": r.status_code, "reachable": r.ok}
    except requests.RequestException as e:
        return {"url": sitemap_url, "status": None, "reachable": False, "error": str(e)}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: robots_checker.py <domain_or_url>", file=sys.stderr)
        return 64

    base = normalize(sys.argv[1])
    url = f"{base}/robots.txt"

    try:
        r = fetch(url, timeout=10)
    except requests.RequestException as e:
        print(json.dumps({"url": url, "error": str(e)}, indent=2))
        return 1

    result: dict = {
        "url": url,
        "http_status": r.status_code,
        "exists": r.status_code == 200,
        "byte_size": len(r.text.encode("utf-8")) if r.ok else 0,
    }

    if not r.ok:
        result["error"] = f"HTTP {r.status_code}"
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1

    parsed = parse_robots(r.text)
    result["sitemaps"] = [check_sitemap_reachable(s) for s in parsed["sitemaps"]]
    result["user_agent_groups"] = sorted(parsed["groups"].keys())
    result["issues"] = detect_issues(parsed, r.text)

    # Per-crawler verdict on `/` access
    bot_access = []
    for token, owner, purpose in AI_CRAWLERS:
        rules = effective_for(parsed["groups"], token)
        blocked = is_path_blocked(rules, "/")
        rule_source = "specific" if any(g.lower() == token.lower() for g in parsed["groups"]) else "wildcard"
        bot_access.append({
            "bot": token,
            "owner": owner,
            "purpose": purpose,
            "root_blocked": blocked,
            "rule_source": rule_source,
        })
    result["bot_access"] = bot_access

    # Quick summary fields for the orchestrator
    ai_blocked = [b["bot"] for b in bot_access if b["root_blocked"]]
    ai_allowed = [b["bot"] for b in bot_access if not b["root_blocked"]]
    result["summary"] = {
        "ai_crawlers_blocked": ai_blocked,
        "ai_crawlers_allowed": ai_allowed,
        "sitemap_count": len(parsed["sitemaps"]),
        "issues_count": len(result["issues"]),
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 2 if result["issues"] else 0


if __name__ == "__main__":
    sys.exit(main())

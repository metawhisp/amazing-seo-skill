#!/usr/bin/env python3
"""
CMS / framework detector for a target URL.

Why it matters for SEO:
  - Tailored recommendations: Yoast on WordPress, Liquid templates on Shopify,
    next-sitemap on Next.js, etc.
  - Known SEO traps per platform: Shopify duplicate-collection paths, Wix
    rendering issues for some content, Webflow CMS pagination limits.
  - Saves the user from generic advice that doesn't apply to their stack.

Detection method:
  Combines three signals — HTML body content, HTTP response headers, and the
  `<meta name="generator">` tag — with weighted matching. Each CMS gets a
  confidence score 0-100; the highest-scoring one wins (with ties broken
  by signal count). The full signal list is reported so the user can
  verify.

Currently detects:
  WordPress, Shopify, Webflow, Wix, Squarespace, Ghost, Drupal, Joomla,
  Magento (Adobe Commerce), HubSpot CMS, Bigcommerce, PrestaShop,
  TYPO3, Sitecore, Contentful, Sanity, Strapi (headless), Next.js,
  Nuxt, Gatsby, Hugo, Jekyll, Astro, Eleventy.

Exit code:
  0 = CMS detected with confidence >= 50
  1 = fetch failed
  2 = unknown CMS or low confidence

Usage:
  cms_detector.py <url>
"""
from __future__ import annotations

import json
import re
import sys

import requests

from _fetch import fetch


# Each entry: (CMS name, body_patterns, header_patterns, generator_patterns, hint_url_segments)
# Patterns are case-insensitive regex (compiled at module load).
_CMS_RULES = [
    ("WordPress", [
        r"/wp-content/", r"/wp-includes/", r"/wp-json/", r"wp-emoji",
        r"<link[^>]+wp-includes", r"id=\"wp-",
    ], [
        ("x-powered-by", r"WordPress"), ("link", r"wp.me"),
    ], [r"WordPress(?:\s|\b)"], ["/wp-admin/", "/wp-login.php"]),

    ("Shopify", [
        r"cdn\.shopify\.com", r"\.myshopify\.com", r"/cdn/shop/",
        r"Shopify\.theme", r"Shopify\.shop", r"Shopify\.routes",
        r"shopify-checkout-api-token", r"Shopify_PaymentButton",
        r"__st\b", r"shopifycloud", r"shopify-features",
    ], [
        ("x-shopify-stage", r".+"), ("x-shopid", r".+"),
        ("x-shardid", r".+"), ("server", r"cloudflare.*shopify"),
        ("x-sorting-hat-podid", r".+"), ("x-shopify-shop-api-call-limit", r".+"),
    ], [r"Shopify"], ["/products/", "/collections/", "/cart/", "/checkout/"]),

    ("Webflow", [
        r"webflow\.com/assets", r"\.webflow\.io", r"data-wf-",
        r"w-mod-", r"class=\"w-",
    ], [("x-webflow-context", r".+")], [r"Webflow"], []),

    ("Wix", [
        r"wixstatic\.com", r"static\.parastorage\.com",
        r"wix\.com/\?utm_source", r"data-wix-",
    ], [("x-wix-request-id", r".+")], [r"Wix\.com"], []),

    ("Squarespace", [
        r"squarespace-cdn\.com", r"squarespace\.com",
        r"static1\.squarespace\.com", r"data-controller=\"PageLoader\"",
    ], [("x-squarespace-request-id", r".+")], [r"Squarespace"], []),

    ("Ghost", [
        r"/content/images/", r"ghost-sdk", r"data-ghost",
    ], [("x-powered-by", r"Express")], [r"Ghost\s+\d"], ["/ghost/"]),

    ("Drupal", [
        r"/sites/default/files/", r"/modules/", r"drupal\.js",
        r"Drupal\.settings",
    ], [("x-generator", r"Drupal"), ("x-drupal-cache", r".+")], [r"Drupal\s+\d"], ["/user/login"]),

    ("Joomla", [
        r"/media/system/", r"/components/com_", r"Joomla!",
    ], [("x-powered-by", r"PHP")], [r"Joomla!"], ["/administrator/"]),

    ("Magento", [
        r"Mage\.Cookies", r"/static/version", r"static/frontend/",
        r"Magento_",
    ], [], [r"Magento"], ["/checkout/cart/"]),

    ("Adobe Commerce", [
        r"AdobeCommerce", r"Adobe Commerce",
    ], [], [r"Adobe\s+Commerce"], []),

    ("HubSpot CMS", [
        r"hs-scripts\.com", r"hubspotusercontent", r"hubspotcms\.com",
        r"hubspot\.com/_hcms",
    ], [("x-hs-ad-id", r".+")], [r"HubSpot"], []),

    ("BigCommerce", [
        r"cdn11?\.bigcommerce\.com", r"bigcommerce-cdn",
    ], [("x-bc-apex-domain", r".+")], [r"BigCommerce"], []),

    ("PrestaShop", [
        r"PrestaShop", r"/themes/[^/]+/assets/",
    ], [("x-powered-by", r"PrestaShop")], [r"PrestaShop"], []),

    ("TYPO3", [
        r"typo3conf/", r"typo3temp/",
    ], [("x-typo3-parsetime", r".+")], [r"TYPO3"], []),

    ("Sitecore", [
        r"/-/media/", r"Sitecore",
    ], [("x-aspnet-version", r".+"), ("x-sitecore", r".+")], [r"Sitecore"], []),

    # Headless / SaaS CMS
    ("Contentful", [
        r"images\.ctfassets\.net", r"contentful",
    ], [], [], []),
    ("Sanity", [
        r"cdn\.sanity\.io",
    ], [], [], []),
    ("Strapi", [
        r"strapi-cdn",
    ], [("x-powered-by", r"Strapi")], [r"Strapi"], []),

    # Static site generators / frameworks (also relevant for SEO advice)
    ("Next.js", [
        r"_next/static", r"__NEXT_DATA__", r"_next/image",
    ], [("x-powered-by", r"Next\.js")], [r"Next\.js"], []),
    ("Nuxt", [
        r"__NUXT__", r"_nuxt/",
    ], [("x-powered-by", r"Nuxt")], [r"Nuxt"], []),
    ("Gatsby", [
        r"___gatsby", r"gatsby-",
    ], [], [r"Gatsby\s+\d"], []),
    ("Hugo", [
        r"<!-- Mirrored from", r"hugo\s+\d",
    ], [], [r"Hugo\s+\d"], []),
    ("Jekyll", [
        r"jekyll-",
    ], [], [r"Jekyll"], []),
    ("Astro", [
        r"astro-island", r"\?astro=",
    ], [], [r"Astro"], []),
    ("Eleventy", [
        r"11ty\.", r"eleventy",
    ], [], [r"Eleventy"], []),
]

# CMS-specific SEO recommendations
_CMS_TIPS = {
    "WordPress": [
        "Use Yoast SEO or Rank Math plugin for metadata management",
        "Enable XML sitemap via plugin; ensure /wp-sitemap.xml is referenced in robots.txt",
        "Watch for orphan attachment pages — set to 'noindex' or redirect",
    ],
    "Shopify": [
        "Avoid duplicate-collection paths — set canonical on filtered URLs",
        "Use Shopify's JSON-LD product templates in theme.liquid",
        "Beware /products/<id> vs /collections/<c>/products/<id> duplication",
    ],
    "Webflow": [
        "CMS collections paginate at 100 items per page — plan accordingly",
        "Sitemap auto-generated; verify it's in robots.txt",
        "Use Webflow's Open Graph tags from CMS fields",
    ],
    "Wix": [
        "Verify rendered HTML (Wix uses heavy client-side JS — run js_rendering_diff.py)",
        "Wix Stores duplicates can be controlled via SEO Pages settings",
    ],
    "Squarespace": [
        "Custom URLs preferred — avoid /pages-id default slugs",
        "Configure 301 redirects via URL Mappings for legacy URLs",
    ],
    "Next.js": [
        "Verify generateMetadata is used for dynamic routes",
        "Sitemap.ts and robots.ts in App Router for SEO basics",
        "Watch for client-side-only data — ensure SSR for critical SEO content",
    ],
    "Drupal": [
        "Pathauto + Metatag modules handle URL/meta automation",
        "Disable taxonomy-term pages if they overlap with content pages",
    ],
    "Magento": [
        "Layered-nav filters generate duplicate URLs — set canonical aggressively",
        "Disable trailing-slash and case variants in URL rewrites",
    ],
    "Ghost": [
        "Built-in SEO is solid; verify image alt text per post",
        "Custom canonical URLs available in post settings",
    ],
}


def _compile_rules():
    """Pre-compile regexes for performance."""
    compiled = []
    for name, body, headers, gens, hints in _CMS_RULES:
        body_compiled = [re.compile(p, re.IGNORECASE) for p in body]
        gen_compiled = [re.compile(p, re.IGNORECASE) for p in gens]
        compiled.append((name, body_compiled, headers, gen_compiled, hints))
    return compiled


_COMPILED = _compile_rules()


def _detect(html: str, headers: dict, final_url: str) -> dict:
    """Score every CMS. Returns dict with sorted candidates."""
    headers_lower = {k.lower(): v for k, v in headers.items()}
    # Extract generator meta tag
    gen_match = re.search(
        r'<meta\s+name=["\']generator["\']\s+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    generator = gen_match.group(1) if gen_match else ""

    candidates = []
    for name, body_pats, header_pats, gen_pats, hints in _COMPILED:
        signals: list[str] = []
        score = 0

        # Body patterns: each match worth 15 points (capped 5 matches = 75 max).
        # Rich-signature CMS like Shopify often hit 8-10 patterns on real stores.
        body_hits = sum(1 for p in body_pats if p.search(html))
        if body_hits:
            score += min(5, body_hits) * 15
            signals.append(f"{body_hits} body pattern(s)")

        # Header patterns: each match worth 35 points (headers are very reliable —
        # platforms send specific X-* headers that aren't easily spoofed)
        for hkey, hpat in header_pats:
            val = headers_lower.get(hkey, "")
            if val and re.search(hpat, val, re.IGNORECASE):
                score += 35
                signals.append(f"header {hkey}={val[:40]}")

        # Generator meta: 50 points (highest confidence — explicit self-declaration)
        for gp in gen_pats:
            if gp.search(generator):
                score += 50
                signals.append(f"generator={generator[:60]}")
                break

        # URL hints (e.g. /wp-admin/): low weight, 10 each
        for hint in hints:
            if hint in final_url:
                score += 10
                signals.append(f"url contains {hint}")

        if score > 0:
            candidates.append({
                "cms": name,
                "score": min(score, 100),
                "signals": signals,
                "tips": _CMS_TIPS.get(name, []),
            })

    candidates.sort(key=lambda c: (-c["score"], -len(c["signals"])))
    return {"generator_meta": generator or None, "candidates": candidates}


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: cms_detector.py <url>", file=sys.stderr)
        return 64

    url = sys.argv[1]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        r = fetch(url, timeout=15)
    except requests.RequestException as e:
        print(json.dumps({"url": url, "error": str(e)}, indent=2))
        return 1

    result = _detect(r.text, dict(r.headers), r.url)
    cands = result["candidates"]
    top = cands[0] if cands else None

    out = {
        "url": url,
        "final_url": r.url,
        "http_status": r.status_code,
        "generator_meta": result["generator_meta"],
        "detected": top["cms"] if top and top["score"] >= 40 else None,
        "confidence": top["score"] if top else 0,
        "top_candidate_signals": top["signals"] if top else [],
        "tailored_tips": top["tips"] if top else [],
        "all_candidates": cands[:5],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    # Threshold 40 — gives benefit of the doubt for custom-CDN deployments where
    # platform-specific URL patterns are obscured.
    return 0 if (top and top["score"] >= 40) else 2


if __name__ == "__main__":
    sys.exit(main())

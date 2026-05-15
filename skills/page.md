---
name: seo-page
description: >
  Deep single-page SEO analysis covering on-page elements, content quality,
  technical meta tags, schema, images, and performance. Use when user says
  "analyze this page", "check page SEO", or provides a single URL for review.
---

# Single Page Analysis

## Fast path — one command

For most use cases, just run the orchestrator. It runs every applicable
L1 checker in parallel and emits a Markdown report with a Health Score:

```
scripts/page_score.py <url>                  # Markdown to stdout
scripts/page_score.py <url> --format json    # structured for piping
scripts/page_score.py <url> --no-psi         # skip CWV (no PSI key)
```

That covers: redirects, security headers, schema, images, broken links,
PSI/CWV, hreflang, llms.txt, on-page HTML. Use the sections below when
you need finer control or only want one specific aspect.

## What to Analyze

### On-Page SEO
- Title tag: 50-60 characters, includes primary keyword, unique
- Meta description: 150-160 characters, compelling, includes keyword
- H1: exactly one, matches page intent, includes keyword
- H2-H6: logical hierarchy (no skipped levels), descriptive
- URL: short, descriptive, hyphenated, no parameters
- Internal links: sufficient, relevant anchor text, no orphan pages
- External links: to authoritative sources, reasonable count

### Content Quality
- Word count vs page type minimums (see quality-gates.md)
- Readability: Flesch Reading Ease score, grade level
- Keyword density: natural (1-3%), semantic variations present
- E-E-A-T signals: author bio, credentials, first-hand experience markers
- Content freshness: publication date, last updated date

### Technical Elements
- Canonical tag: present, self-referencing or correct
- Meta robots: index/follow unless intentionally blocked
- Open Graph: og:title, og:description, og:image, og:url
- Twitter Card: twitter:card, twitter:title, twitter:description
- Hreflang: if multi-language, correct implementation

### Schema Markup
- Detect all types (JSON-LD preferred)
- Validate required properties
- Identify missing opportunities
- NEVER recommend HowTo (deprecated) or FAQ (restricted to gov/health)

### Images
- Alt text: present, descriptive, includes keywords where natural
- File size: flag >200KB (warning), >500KB (critical)
- Format: recommend WebP/AVIF over JPEG/PNG
- Dimensions: width/height set for CLS prevention
- Lazy loading: loading="lazy" on below-fold images

### Core Web Vitals
For real measurements, run the deterministic checker:
```
scripts/psi_checker.py <url>            # mobile (default, matches Google's mobile-first index)
scripts/psi_checker.py <url> --desktop  # desktop strategy
```
Returns CrUX field 75th-percentile LCP/INP/CLS/FCP/TTFB when available, plus
Lighthouse lab data, with per-metric verdicts.

Without measurements (e.g. PSI quota exhausted), use HTML-only heuristics:
- Flag potential LCP issues (huge hero images, render-blocking resources)
- Flag potential INP issues (heavy JS, no async/defer)
- Flag potential CLS issues (missing image dimensions, injected content)

## Output

### Page Score Card
```
Overall Score: XX/100

On-Page SEO:     XX/100  ████████░░
Content Quality: XX/100  ██████████
Technical:       XX/100  ███████░░░
Schema:          XX/100  █████░░░░░
Images:          XX/100  ████████░░
```

### Issues Found
Organized by priority: Critical → High → Medium → Low

### Recommendations
Specific, actionable improvements with expected impact

### Schema Suggestions
Ready-to-use JSON-LD code for detected opportunities

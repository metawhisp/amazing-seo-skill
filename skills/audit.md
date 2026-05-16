---
name: seo-audit
description: >
  Full website SEO audit with parallel subagent delegation. Crawls up to 500
  pages, detects business type, delegates to 6 specialists, generates health
  score. Use when user says "audit", "full SEO check", "analyze my site",
  or "website health check".
---

# Full Website SEO Audit

## Fast path — one command

For most audits, run the site orchestrator (parallelises `page_score.py`
across N URLs sampled from the sitemap and emits a single Markdown report):

```
tools/site_audit.sh <domain> --limit 20 > REPORT.md
tools/site_audit.sh <domain> --limit 50 --no-psi    # faster, no CWV
```

The report includes overall Health Score, category averages, top recurring
findings across pages, under-performers (>1σ below mean), and per-page
summary. Use the detailed process below when you need editorial control or
specific category deep-dives.

## Process

1. **Crawl** (FIRST STEP — use the smart dispatcher):

   ```bash
   tools/crawl.sh https://TARGET_DOMAIN --max-pages 5000
   ```

   The dispatcher auto-selects:
   - **Screaming Frog** if installed and ≤500 URLs (better data quality)
   - **amazing-crawl** (our async Python crawler) otherwise — unlimited URLs,
     no GUI required, works in CI/Docker, free.

   Force the choice with `--force-sf` or `--force-amazing`. Results land
   in CSV/SQLite for downstream analysis steps.

2. **Fetch homepage** — use `curl` to retrieve HTML for business type detection
3. **Detect business type** — analyze homepage signals per seo orchestrator
4. **Analyze SF crawl data** — parse CSVs for status codes, titles, H1, canonicals, directives, schema
5. **Delegate to subagents** (if available, otherwise run inline sequentially):
   - `seo-technical` — robots.txt, sitemaps, canonicals, Core Web Vitals, security headers
   - `seo-content` — E-E-A-T, readability, thin content, AI citation readiness
   - `seo-schema` — detection, validation, generation recommendations
   - `seo-sitemap` — structure analysis, quality gates, missing pages
   - `seo-performance` — LCP, INP, CLS measurements
   - `seo-visual` — screenshots, mobile testing, above-fold analysis
6. **Ahrefs data** (if Ahrefs MCP available — always use when connected):
   - `site-explorer-metrics` — DR, organic traffic, keywords count
   - `site-explorer-organic-keywords` — top ranking keywords
   - `site-explorer-top-pages` — pages by traffic
   - `site-explorer-pages-by-backlinks` — pages with most backlinks
   - `site-explorer-organic-competitors` — who competes for same keywords
   - `site-explorer-backlinks-stats` — backlink profile overview
   - `site-explorer-referring-domains` — referring domain list
   - `keywords-explorer-overview` — keyword difficulty, volume
   - `keywords-explorer-matching-terms` — keyword ideas
   Cross-reference Ahrefs data with SF crawl: pages with traffic but technical issues = priority fixes.
7. **Score** — aggregate into SEO Health Score (0-100)
8. **Report** — generate prioritized action plan

## Crawl Configuration

```
Max pages: 500
Respect robots.txt: Yes
Follow redirects: Yes (max 3 hops)
Timeout per page: 30 seconds
Concurrent requests: 5
Delay between requests: 1 second
```

## Output Files

- `FULL-AUDIT-REPORT.md` — Comprehensive findings
- `ACTION-PLAN.md` — Prioritized recommendations (Critical → High → Medium → Low)
- `screenshots/` — Desktop + mobile captures (if Playwright available)

## Scoring Weights

**Source of truth: `scripts/page_score.py:CHECKERS`.**

| Category | Weight | Checkers |
|----------|--------|----------|
| Technical | 20% | redirects + security headers |
| Schema | 15% | schema required+recommended fields |
| Images | 15% | alt / format / dims / lazy |
| Links | 15% | broken links per page |
| Performance (CWV) | 15% | PageSpeed Insights field+lab |
| Content | 10% | Flesch + E-E-A-T + density |
| GEO | 10% | hreflang + llms.txt |
| Informational | 0% | parse_html + cms_detector (no score impact) |

## Report Structure

### Executive Summary
- Overall SEO Health Score (0-100)
- Business type detected
- Top 5 critical issues
- Top 5 quick wins

### Technical SEO
- Crawlability issues
- Indexability problems
- Security concerns
- Core Web Vitals status

### Content Quality
- E-E-A-T assessment
- Thin content pages
- Duplicate content issues
- Readability scores

### On-Page SEO
- Title tag issues
- Meta description problems
- Heading structure
- Internal linking gaps

### Schema & Structured Data
- Current implementation
- Validation errors
- Missing opportunities

### Performance
- LCP, INP, CLS scores
- Resource optimization needs
- Third-party script impact

### Images
- Missing alt text
- Oversized images
- Format recommendations

### AI Search Readiness
- Citability score
- Structural improvements
- Authority signals

## Priority Definitions

- **Critical**: Blocks indexing or causes penalties (fix immediately)
- **High**: Significantly impacts rankings (fix within 1 week)
- **Medium**: Optimization opportunity (fix within 1 month)
- **Low**: Nice to have (backlog)

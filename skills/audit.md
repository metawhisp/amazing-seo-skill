---
name: seo-audit
description: >
  Full website SEO audit with parallel subagent delegation. Crawls up to 500
  pages, detects business type, delegates to 6 specialists, generates health
  score. Use when user says "audit", "full SEO check", "analyze my site",
  or "website health check".
---

# Full Website SEO Audit

## Process

1. **Screaming Frog crawl** (FIRST STEP — always run if SF is installed):
   ```bash
   SF="/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher"
   timeout 600 "$SF" \
     --crawl "https://TARGET_DOMAIN" \
     --headless \
     --output-folder /tmp/sf-crawl/TARGET_DOMAIN \
     --export-tabs "Internal:All,Response Codes:All,Page Titles:All,Page Titles:Duplicate,Meta Description:All,Meta Description:Missing,Meta Description:Duplicate,H1:All,H1:Duplicate,H1:Missing,H2:All,H2:Duplicate,Canonicals:All,Directives:All,Hreflang:All,Images:Missing Alt Text,Structured Data:All" \
     --overwrite 2>&1 | grep -E "SpiderProgress|Completed|Exporting|ERROR|FATAL"
   ```
   Then parse the CSV results and use them as the data source for all subsequent analysis steps. See `seo-screaming-frog` skill for full reference.

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
5. **Ahrefs data** (if Ahrefs MCP available — always use when connected):
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
6. **Score** — aggregate into SEO Health Score (0-100)
7. **Report** — generate prioritized action plan

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

| Category | Weight |
|----------|--------|
| Technical SEO | 25% |
| Content Quality | 25% |
| On-Page SEO | 20% |
| Schema / Structured Data | 10% |
| Performance (CWV) | 10% |
| Images | 5% |
| AI Search Readiness | 5% |

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

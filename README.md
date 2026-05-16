# Amazing SEO Skill — SEO + AEO + GEO Audit for Claude Code

The most comprehensive SEO skill for Claude Code: traditional SEO audit, AI
Overviews readiness (GEO), live LLM citation tracking (AEO), Schema.org
validation, real-browser Core Web Vitals, internal link graph analysis, and
data-driven growth opportunities — all from a single Claude Code prompt.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-purple)](https://docs.claude.com/en/docs/claude-code)
[![SEO + AEO + GEO](https://img.shields.io/badge/SEO%20%2B%20AEO%20%2B%20GEO-✓-green)]()

> **Why this exists.** Standard SEO tools tell you a site is "92/100" while
> ChatGPT, Perplexity, Claude, and Grok don't cite it once for any of its core
> queries. This skill closes the gap by combining traditional SEO checks with
> live AI-search visibility testing.

## What it does

### Traditional SEO
- **Smart crawler** via `tools/crawl.sh` — auto-selects between Screaming Frog (≤500 URLs free tier) and our own **`amazing-crawl`** (async Python, unlimited URLs, no GUI, works in CI/Docker)
- **Full website audits** via `tools/site_audit.sh` — parallelises per-page audits across sampled sitemap URLs, emits unified Markdown report
- **Single-page Health Score** via `scripts/page_score.py` — every L1 check on one URL, aggregated 0-100 with prioritized findings
- **HTML visual report** via `scripts/render_html_report.py` — styled standalone HTML for stakeholder sharing
- **Static dashboard** via `scripts/build_dashboard.py` + `tools/serve_dashboard.sh` — multi-domain overview with trend sparklines, runs history, drillable run-detail pages. No backend, no daemon, no cloud — opens locally or deploys to any static host.
- **Audit history** via `scripts/audit_history.py` — SQLite store, score trends, diff between runs
- **CMS / framework detection** — 24+ platforms (WordPress, Shopify, Webflow, Wix, Squarespace, Ghost, Drupal, Magento, HubSpot, BigCommerce, Next.js, Nuxt, Gatsby, Hugo, Astro, ...) with tailored SEO tips per platform
- **JS rendering diff** — server-side HTML vs Playwright-rendered HTML structural comparison (canonical/robots/title/meta/schema deltas). Critical for SPA SEO
- **Server log analysis** — Apache/Nginx logs (incl `.gz`): bot breakdown, crawl waste, error spikes, sitemap orphans/cold pages
- **Real Core Web Vitals** via PageSpeed Insights API (CrUX field LCP/INP/CLS/FCP/TTFB at 75th-pct + Lighthouse lab)
- **Security headers** — HSTS, CSP (with nonce/hash detection), X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, mixed-content scan
- **Schema.org validation** — required AND recommended fields per item, per-item 0-100 completeness, list of missing field names
- **Broken-link checker** — every `<a>`, `<link>`, `<script>`, `<img>`, `<source>`, `<iframe>`, CSS bg; splits 4xx vs 5xx vs auth-gated 401/403
- **Image audit** — alt coverage, format mix (WebP/AVIF vs ≥70% target), width/height for CLS, lazy on below-fold, size flags
- **Content quality** — Flesch reading ease, sentence/paragraph length, keyword stuffing detection, AI-generation marker phrases, 134-200 word citable-passage extraction for AI Overviews, author byline + dates
- **Local SEO** — NAP discoverability, LocalBusiness schema fields, Google Maps embed, GBP / Yelp / BBB citations, NAP consistency
- **SerpAPI integration** (optional) — top-10 organic, SERP features, AI Overview citation check
- **Hreflang / international SEO** — BCP-47, x-default, self-reference, parallel reciprocity validation
- **Internal link graph analysis** — true-orphan detection, hub mapping, dead-end pages
- **Sitemap validator** — XML validity, sitemap-index recursion, 50k URL / 50 MiB limits, HTTPS-only, lastmod sanity, deprecated tags, sample HTTP-200, robots cross-check
- **Robots.txt + AI crawlers** — per-bot Allow/Disallow for 20 crawlers (GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, Claude-User, PerplexityBot, Google-Extended, meta-externalagent, Bytespider, etc.)
- **Redirect chains** — per-hop trace, HTTP→HTTPS upgrade, 301/302 mix, loop detection, canonical alignment

### AI search optimization (the new layer)
- **AI Visibility Score** via `scripts/ai_visibility_score.py` — composite 0-100 across 6 components (AI crawler accessibility, SSR completeness, schema, llms.txt, hreflang, live Gemini citations)
- **AEO — Answer Engine Optimization.** Live citation testing: query 5 LLM
  surfaces (ChatGPT, Claude, Perplexity, Grok, **and Gemini with Google
  Search grounding** — the closest publicly-available proxy for Google AI
  Overviews / AI Mode) for your target queries and report which providers
  cite your domain.
- **GEO — Generative Engine Optimization.** Optimize for Google AI Overviews,
  ChatGPT search, Perplexity search, and other generative answer engines.
- **`llms.txt` validation** — checks existence, structure, AEO-language
  signals, recommended sections.
- **AI bot accessibility** — verifies `GPTBot`, `ClaudeBot`, `PerplexityBot`,
  `Google-Extended`, `Apple-Extended` access in `robots.txt`.

### Content quality (E-E-A-T)
- **E-E-A-T framework** per the September 2025 Quality Rater Guidelines update
- Author bylines, content dates, citations to authoritative sources
- Reading level, word count, keyword stuffing, link density, text-to-HTML ratio
- Industry-specific quality gates (SaaS, e-commerce, local, publisher, agency)

### Growth (not just audit)
- **Competitor keyword gap analysis** via the backlink/keyword data layer
- **Top competitor pages by organic traffic** to identify content types you're
  missing (comparison pages, alternatives pages, listicles, glossary)
- **Opportunity scoring by impact ÷ effort** with KD (keyword difficulty)
  filters
- **Programmatic SEO planning** with thin-content safeguards

## Why use this skill

| | Standard SEO tools | Amazing SEO Skill |
|---|---|---|
| Findings per audit | 5–20 high-level | 50+ specific, actionable |
| Real Core Web Vitals | Often missing | ✓ Playwright in-browser |
| Schema recommended fields | "X missing" | Names every missing field |
| Live LLM citation testing | ✗ | ✓ ChatGPT + Perplexity + Claude + Grok |
| Internal link graph | ✗ | ✓ true-orphan detection |
| Multi-page audit | Premium tier | ✓ free, scriptable |
| Industry templates | Generic | 6 templates: SaaS, e-com, local, publisher, agency, generic |
| Output format | Dashboard | Structured Markdown + JSON for piping |
| Run as Claude Code skill | ✗ | ✓ |
| Cost | $99–$999/mo | Free + your own API keys |

## Architecture — 4-layer data model

| Layer | Source | Purpose |
|-------|--------|---------|
| L0 | Claude reasoning + WebFetch | Analysis, prioritization, recommendations |
| L1 | Python scripts (~29 deterministic checkers) | Reproducible verdicts on robots, sitemap, redirects, security headers, broken links, images, hreflang, schema, llms.txt, internal links, CWV, CMS detection, JS rendering, content quality, local SEO, log analysis, AI visibility |
| L2 | Local CLI engines (configurable) | Real-browser CWV, 251-rule deep audit, live AEO citations |
| L3 | External APIs (Ahrefs, GSC) | Backlink data, real keyword performance |
| L4 | Multi-LLM ensemble (Anthropic, OpenAI, Perplexity, xAI, Google Gemini-with-Search) | Live AEO citation testing across all major AI surfaces |

Each finding carries a confidence label: **Confirmed** (data-backed),
**Likely** (data + reasoning), **Hypothesis** (reasoning fallback).

## Installation

### Lightweight mode (reasoning only — works on any Claude Code install)

```bash
git clone https://github.com/metawhisp/amazing-seo-skill.git \
  ~/.claude/skills/amazing-seo-skill
```

Then in Claude Code, just say `сделай SEO аудит example.com` or
`audit https://example.com` and the skill activates via its trigger keywords.

### Check what's active

After install, run the onboarding wizard — it probes prereqs, API keys,
and runs live smoke tests, then reports which layers (L0-L4) you have:

```bash
cd ~/.claude/skills/amazing-seo-skill
./tools/onboarding.sh
```

See [ONBOARDING.md](ONBOARDING.md) for the full reference: what each layer
unlocks, how to add API keys, troubleshooting.

### Full mode (all 4 layers, real CWV + live AEO)

```bash
git clone https://github.com/metawhisp/amazing-seo-skill.git \
  ~/.claude/skills/amazing-seo-skill
cd ~/.claude/skills/amazing-seo-skill

# Set engine package identifiers (your choice — installer is engine-agnostic)
DEEP_AUDIT_ENGINE_PKG="<npm-pkg-for-deep-audit>" \
DEEP_AUDIT_ENGINE_BIN_NAME="<bin-name>" \
AEO_CITATIONS_ENGINE_PKG_SPEC="<pip-spec-for-aeo>" \
AEO_CITATIONS_ENGINE_BIN_NAME="<bin-name>" \
AEO_CITATIONS_ENGINE_CONFIG_FILENAME="<config-filename>" \
./install.sh
```

For live AEO citation testing across 5 LLM surfaces, store API keys in
macOS Keychain:

```bash
security add-generic-password -s anthropic-api-key      -a $USER -w
security add-generic-password -s openai-api-key         -a $USER -w
security add-generic-password -s perplexity-api-key     -a $USER -w
security add-generic-password -s x.ai-api-key           -a $USER -w
security add-generic-password -s google-gemini-api-key  -a $USER -w  # Gemini + Google Search grounding (AI Overviews proxy)
```

For real Core Web Vitals via PageSpeed Insights API (improves rate limit
from ~25/day keyless to ~25,000/day), also add:

```bash
security add-generic-password -s google-psi-api-key     -a $USER -w
```

## Usage

Just describe what you want. Claude picks up the skill automatically via
trigger keywords:

```
audit https://example.com                        — full site audit
page https://example.com/blog/post               — single-page deep analysis
technical https://example.com                    — technical SEO only
schema https://example.com                       — Schema.org validation
geo https://example.com                          — AI Overviews readiness
aeo https://example.com "best email tool"        — live LLM citation check
hreflang https://example.com                     — i18n / hreflang validation
growth https://example.com                       — competitor gap + opportunities
plan saas                                        — strategic planning
competitor-pages generate                        — comparison page templates
```

Output: **SEO Health Score (0–100)** + prioritized action plan
(Critical / High / Medium / Low) with confidence labels.

## Use cases

- **Pre-launch audit** before shipping a new site or major redesign
- **Quarterly SEO review** with month-over-month tracking
- **AI search visibility audit** — find out if your domain is actually cited
  by ChatGPT / Perplexity / Claude / Grok
- **Competitor research** for content strategy
- **Schema markup migration** when moving CMS or redesigning templates
- **International SEO** before launching new locale versions
- **Programmatic SEO planning** — quality gates prevent thin-content traps

## Industry templates

Built-in playbooks for 6 business types under `industry/`:

- **SaaS** — pricing, features, integrations, free trial signals
- **E-commerce** — product schema, faceted nav, OOS handling
- **Local service** — NAP, LocalBusiness schema, service-area pages
- **Publisher** — Article schema, author E-E-A-T, content velocity
- **Agency** — case studies, portfolio, industry pages
- **Generic** — fallback for hybrid models

The orchestrator auto-detects business type from homepage signals and applies
the right template.

## Trigger keywords

The skill activates automatically when any of these appear in your prompt:
`SEO`, `audit`, `schema`, `structured data`, `JSON-LD`, `Core Web Vitals`,
`INP`, `LCP`, `CLS`, `sitemap`, `E-E-A-T`, `AI Overviews`, `GEO`, `AEO`,
`technical SEO`, `content quality`, `page speed`, `hreflang`, `programmatic
SEO`, `competitor pages`, `growth opportunities`, `keyword gap`,
`llms.txt`, `AI search`, `LLM citations`.

## Repository layout

```
amazing-seo-skill/
├── SKILL.md            # entry-point orchestrator (auto-loaded by Claude)
├── README.md           # this file
├── install.sh          # full-mode installer (engine-agnostic)
├── skills/             # 13 sub-skill modules — each works standalone too
├── agents/             # parallel sub-agents (growth-finder)
├── scripts/            # Python deterministic checkers
├── tools/              # user-facing wrappers (cwv-checker, aeo-citations, ...)
├── .bin/               # internal engine wrappers (env-driven, brand-neutral)
├── integrations/       # Ahrefs, GSC integration guides
├── references/         # CWV thresholds, E-E-A-T, quality gates, schema types
├── industry/           # 6 industry templates
├── schema/             # JSON-LD templates
├── hooks/              # optional pre-commit SEO validation
└── docs/               # reference docs
```

## Status

Active development. v0.7 series — 29 deterministic checkers + 6 orchestrator
tools, all verified end-to-end on production sites. See [releases](https://github.com/metawhisp/amazing-seo-skill/releases) for changelog.

## Contributing

Issues and pull requests welcome. The skill is intentionally **engine-
agnostic**: deep-audit and AEO-citations engines are configured per-environment,
so you can swap implementations without forking.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

## Tags

`seo` `seo-audit` `ai-seo` `aeo` `geo` `claude-code` `claude-skill`
`anthropic` `llm` `structured-data` `schema-markup` `schema-org`
`core-web-vitals` `ai-overviews` `chatgpt-seo` `perplexity-seo`
`generative-engine-optimization` `answer-engine-optimization`
`technical-seo` `hreflang`

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
- **Full website audits** with parallel sub-agent delegation across 8 categories
- **Real-browser Core Web Vitals** (LCP, CLS, FCP, TTFB, INP) via Playwright
- **Schema.org validation** — required AND recommended fields per item, with
  explicit lists of what's missing (not just counts)
- **Hreflang / international SEO** — BCP-47, x-default, self-reference,
  reciprocity validation
- **Internal link graph analysis** — true-orphan detection, hub mapping,
  dead-end pages
- **Multi-page audits** across whole sitemap with statistical aggregation
- **Sitemap, robots.txt, redirect chains, canonical** validation
- **Image optimization** — alt text, formats (WebP/AVIF), lazy-loading, CLS
  prevention
- **Mobile, URL structure, security headers (HSTS, CSP), accessibility (WCAG)**

### AI search optimization (the new layer)
- **AEO — Answer Engine Optimization.** Live citation testing: query 4 LLM
  providers (ChatGPT, Perplexity, Claude, Grok) for your target queries and
  report which providers cite your domain.
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
| L1 | Python scripts (~10 deterministic checkers) | Reproducible verdicts on robots, hreflang, schema, llms.txt, internal links |
| L2 | Local CLI engines (configurable) | Real-browser CWV, 251-rule deep audit, live AEO citations |
| L3 | External APIs (Ahrefs, GSC) | Backlink data, real keyword performance |
| L4 | Multi-LLM ensemble (Anthropic, OpenAI, Perplexity, xAI) | Live AEO citation testing |

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

For live AEO citation testing across 4 LLM providers, store API keys in
macOS Keychain:

```bash
security add-generic-password -s anthropic-api-key   -a $USER -w
security add-generic-password -s openai-api-key      -a $USER -w
security add-generic-password -s perplexity-api-key  -a $USER -w
security add-generic-password -s x.ai-api-key        -a $USER -w
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
├── agents/             # parallel sub-agents (verifier, growth-finder, ...)
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

Active development. v0.2 series — calibrated against real production sites,
all 6 deterministic checkers verified end-to-end. See commit history for
release notes.

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

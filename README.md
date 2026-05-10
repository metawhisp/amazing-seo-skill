# Amazing SEO Skill

Comprehensive SEO + AEO + GEO analysis skill for Claude Code. Works with any
website or business type — SaaS, e-commerce, local service, publisher, agency.

## What it does

- Full website audits with parallel sub-agent delegation
- Single-page deep analysis
- Technical SEO across 8 categories (crawlability, indexability, security,
  Core Web Vitals with INP, JS-rendering, mobile, URL structure, structured
  data)
- Content quality with E-E-A-T framework (Sept 2025 QRG update)
- Schema markup detection, validation, and generation (JSON-LD)
- Image optimization (alt text, formats, lazy-loading, CLS prevention)
- Sitemap analysis and generation with industry templates
- Hreflang / international SEO validation
- Programmatic SEO planning with quality gates
- Competitor comparison page generation
- **GEO (Generative Engine Optimization)** for AI Overviews and AI search
- **AEO (Answer Engine Optimization)** with live LLM citation testing across
  4 providers

## Architecture

Four-layer data model from cheap to expensive:

| Layer | Source | Purpose |
|-------|--------|---------|
| L0 | LLM reasoning + WebFetch | Analysis, prioritization, recommendations |
| L1 | Python scripts | Deterministic checkers |
| L2 | Local CLI engines | Real-browser CWV, deep audit, live AEO citations |
| L3 | External APIs | Backlink data, search console |
| L4 | Multi-LLM ensemble | Cross-validation across 4 LLM providers |

## Installation

### Lightweight (reasoning-only)

Drop `SKILL.md` and `skills/*.md` into `~/.claude/skills/amazing-seo-skill/`.
Works via Claude reasoning + `WebFetch`. No Python, no external CLIs.

### Full (all 4 layers)

```bash
git clone https://github.com/metawhisp/amazing-seo-skill.git \
  ~/.claude/skills/amazing-seo-skill
cd ~/.claude/skills/amazing-seo-skill
./install.sh
```

For multi-LLM ensemble (L4), store API keys in macOS Keychain under these
service names:

```bash
security add-generic-password -s anthropic-api-key   -a $USER -w
security add-generic-password -s openai-api-key      -a $USER -w
security add-generic-password -s perplexity-api-key  -a $USER -w
security add-generic-password -s x.ai-api-key        -a $USER -w
```

## Usage

Invoke from Claude Code by mentioning any trigger keyword (`SEO`, `audit`,
`schema`, `Core Web Vitals`, `AEO`, `GEO`, `hreflang`, etc.) or by calling a
specific module:

```
audit https://example.com
page https://example.com/some-page
technical https://example.com
schema https://example.com
geo https://example.com
aeo https://example.com "best email marketing tool"
plan saas
```

Output: SEO Health Score (0-100) + prioritized action plan
(Critical / High / Medium / Low) with confidence labels (Confirmed / Likely
/ Hypothesis).

## Repository Layout

```
amazing-seo-skill/
├── SKILL.md            # entry-point orchestrator
├── README.md           # this file
├── install.sh          # one-command setup for full mode
├── skills/             # 12 sub-skill modules
├── agents/             # parallel sub-agents (verifier, growth-finder, ...)
├── scripts/            # Python deterministic checkers
├── tools/              # user-facing wrappers around internal engines
├── .bin/               # internal engine wrappers (not user-facing)
├── integrations/       # external API integration guides
├── references/         # CWV thresholds, E-E-A-T, quality gates, schema types
├── industry/           # 6 industry templates
├── schema/             # JSON-LD templates
├── hooks/              # pre-commit hooks for SEO validation
└── docs/               # reference docs
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).

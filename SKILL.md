---
name: amazing-seo-skill
description: >
  Comprehensive SEO + AEO + GEO analysis skill for any website or business type
  (SaaS, e-commerce, local service, publisher, agency). Performs full website
  audits, single-page deep analysis, technical SEO checks (crawlability,
  indexability, Core Web Vitals with INP, JS-rendering diff), schema markup
  detection/validation/generation, content quality assessment with E-E-A-T
  framework, image optimization, sitemap analysis, hreflang/i18n validation,
  programmatic SEO planning, competitor comparison page generation, and
  Generative/Answer Engine Optimization (AI Overviews, ChatGPT, Perplexity,
  Claude citations). Detects business type and applies industry-specific
  thresholds. Uses 4-layer data model: LLM reasoning, deterministic Python
  checkers, real-browser CWV measurement, multi-LLM ensemble cross-validation
  via Anthropic + OpenAI + Perplexity + xAI APIs. Triggers on: "SEO", "audit",
  "schema", "Core Web Vitals", "INP", "sitemap", "E-E-A-T", "AI Overviews",
  "GEO", "AEO", "technical SEO", "content quality", "page speed", "structured
  data", "hreflang", "programmatic SEO", "competitor pages".
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - WebFetch
  - WebSearch
---

# Amazing SEO Skill

Single entry-point orchestrator for end-to-end SEO/AEO/GEO analysis across all
industries. Combines reasoning, deterministic checkers, real-browser
measurement, and multi-LLM cross-validation into one unified workflow.

## Quick Reference

| Command | What it does |
|---------|--------------|
| `audit <url>` | Full website audit, all layers, parallel sub-agents, Health Score |
| `page <url>` | Deep single-page analysis |
| `technical <url>` | Technical SEO across 8 categories |
| `content <url>` | Content quality + E-E-A-T evaluation |
| `schema <url>` | Detect, validate, generate Schema.org markup |
| `images <url>` | Image optimization analysis |
| `sitemap <url \| generate>` | Analyze or generate XML sitemaps |
| `geo <url>` | AI Overviews / Generative Engine Optimization |
| `aeo <url> [keyword]` | Live AEO citation check (4-LLM ensemble) |
| `plan <industry>` | Strategic SEO plan from industry template |
| `programmatic [url \| plan]` | Programmatic SEO analysis or planning |
| `competitor-pages [url \| generate]` | Competitor comparison page generation |
| `hreflang [url]` | Hreflang/i18n SEO audit and generation |
| `growth <url>` | Growth opportunities vs competitors (Ahrefs gap) |

## Architecture: 4-Layer Data Model

| Layer | Source | When to use |
|-------|--------|-------------|
| L0 | Claude reasoning + WebFetch | Analysis, prioritization, recommendations |
| L1 | Python scripts in `scripts/` | Deterministic checkers (robots, hreflang, schema, llms.txt) |
| L2 | Local CLIs in `.bin/` | 251-rule deep audit + real-browser CWV; live AEO citations |
| L3 | External APIs | Ahrefs MCP, Google Search Console |
| L4 | Multi-LLM ensemble | Cross-validation via 4 LLM providers (anthropic, openai, perplexity, xai) |

API keys for L4 are read from macOS Keychain at runtime:
`anthropic-api-key`, `openai-api-key`, `perplexity-api-key`, `x.ai-api-key`.
Retrieve with `security find-generic-password -s <name> -w`.

## Orchestration Logic

When invoked with `audit`, delegate to sub-agents in parallel:

1. Detect business type from homepage signals (SaaS, local, ecommerce, publisher, agency, generic)
2. Spawn parallel sub-agents:
   - `technical` — crawlability, indexability, security, CWV
   - `content` — E-E-A-T, readability, thin content
   - `schema` — detection, validation, generation
   - `sitemap` — structure, coverage, quality gates
   - `performance` — Core Web Vitals via real browser
   - `visual` — screenshots, mobile testing, above-fold
3. Run Verifier agent: dedupe contradictions across sub-agent reports
4. Generate unified report:
   - SEO Health Score (0-100)
   - Findings table with confidence labels (Confirmed / Likely / Hypothesis)
   - Prioritized action plan (Critical → High → Medium → Low)

For individual commands, load the relevant module from `skills/` directly.

## Industry Detection

Identify business type from homepage signals:

- **SaaS** — pricing page, /features, /integrations, /docs, "free trial", "sign up"
- **Local Service** — phone number, address, service area, "serving [city]", Google Maps embed
- **E-commerce** — /products, /collections, /cart, "add to cart", Product schema
- **Publisher** — /blog, /articles, /topics, Article schema, author pages, publication dates
- **Agency** — /case-studies, /portfolio, /industries, "our work", client logos

Apply industry-specific thresholds and templates from `industry/<type>.md`.

## Quality Gates (hard rules)

Read `references/quality-gates.md` for thin-content thresholds per page type.
Hard rules that override any contrary suggestion:

- ⚠️ WARNING at 30+ location pages (enforce 60%+ unique content)
- 🛑 HARD STOP at 50+ location pages (require user justification)
- Never recommend HowTo schema (deprecated September 2023)
- FAQ schema only for government and healthcare sites
- All Core Web Vitals references use INP, never FID
- Never suggest doorway pages or thin content at scale

## Reference Files

Load these on-demand as needed — do NOT load all at startup:

- `references/cwv-thresholds.md` — Current Core Web Vitals thresholds (LCP, CLS, INP)
- `references/schema-types.md` — All supported schema types with deprecation status
- `references/eeat-framework.md` — E-E-A-T evaluation criteria (Sept 2025 QRG update)
- `references/quality-gates.md` — Content length minimums, uniqueness thresholds
- `industry/<type>.md` — Industry template for detected business type
- `docs/google-seo-reference.md` — Google search documentation reference

## Modules (sub-skills)

Each module is a self-contained sub-skill in `skills/*.md`. Load only the
relevant ones for the current task:

| Module | File | Scope |
|--------|------|-------|
| Audit orchestrator | `skills/audit.md` | Full website audit with parallel delegation |
| Page deep-dive | `skills/page.md` | Single-page analysis |
| Technical SEO | `skills/technical.md` | 8 technical categories |
| Content quality | `skills/content.md` | E-E-A-T + readability |
| Schema markup | `skills/schema.md` | Detection, validation, generation |
| Image optimization | `skills/images.md` | Alt text, formats, lazy-loading |
| Sitemap | `skills/sitemap.md` | Analysis and generation |
| GEO / AI Overviews | `skills/geo.md` | Generative Engine Optimization |
| Strategic planning | `skills/plan.md` | Industry-specific plans |
| Programmatic SEO | `skills/programmatic.md` | Scale page generation safely |
| Competitor pages | `skills/competitor-pages.md` | "X vs Y" / "alternatives to X" |
| Hreflang / i18n | `skills/hreflang.md` | International SEO |

## Scoring Methodology

### SEO Health Score (0-100)

Weighted aggregate across categories:

| Category | Weight |
|----------|--------|
| Technical SEO | 25% |
| Content Quality | 25% |
| On-Page SEO | 20% |
| Schema / Structured Data | 10% |
| Performance (CWV) | 10% |
| Images | 5% |
| AI Search Readiness | 5% |

### Priority Levels

- **Critical** — blocks indexing or causes penalties (immediate fix)
- **High** — significantly impacts rankings (fix within 1 week)
- **Medium** — optimization opportunity (fix within 1 month)
- **Low** — nice to have (backlog)

### Confidence Labels (for findings)

- **Confirmed** — verified by deterministic check (L1) or real-browser
  measurement (L2)
- **Likely** — supported by reasoning (L0) and at least one external signal
- **Hypothesis** — based on reasoning alone, requires validation

## Output Formats

- **Markdown report** — human-readable summary
- **JSON** — structured for programmatic processing
- **LLM-XML** — optimized for handoff to another agent

## Internal Engines

Heavy lifting is done by underlying engines, hidden behind brand-neutral
wrappers in `.bin/`. Modules invoke these via `tools/*` rather than calling
external CLIs directly:

- `.bin/_engine_deep_audit` — 251-rule deterministic audit + real-browser CWV
- `.bin/_engine_aeo_citations` — live LLM citation checking

## Execution Mode (dual)

This skill supports two installation modes:

- **Lightweight** — only `SKILL.md` and `skills/*.md` are present. All analysis
  happens via Claude reasoning + `WebFetch`. No Python or external CLIs needed.
- **Full** — full repo cloned. All 4 layers active, including deterministic
  checkers, real-browser CWV, AEO citations, and multi-LLM ensemble.

Detect mode at runtime: if `.venv/bin/python` exists → full mode; otherwise
lightweight.

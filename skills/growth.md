---
name: growth
description: >
  Growth-loop sub-skill. Goes beyond SEO audit: identifies concrete growth
  opportunities by comparing target site to its competitors. Pulls keyword
  gaps, top competitor pages, content types competitors rank for but you
  don't, and prioritizes by traffic potential vs effort. Triggers on:
  "growth", "точки роста", "competitor gap", "keyword gap", "what to write
  about", "outrank", "opportunity".
allowed-tools:
  - Read
  - Bash
  - WebFetch
---

# Growth — Find concrete opportunities, not just problems

Audit tells you what is broken. Growth tells you **what to build**.

This sub-skill compares a target domain to its competitors via the backlink/
keyword data layer (L3) and surfaces actionable opportunities ranked by
estimated impact.

## When to invoke

- User asks for "growth opportunities", "точки роста", "where to invest"
- Audit (`/amazing-seo audit`) finished and target wants next steps beyond
  fixing issues
- User mentions a competitor name explicitly ("how to outrank X")
- Quarterly content planning context

## Inputs

| Required | Source |
|---|---|
| Target domain | User-provided or detected from audit |
| Competitor list | User-provided OR derived (see "Competitor discovery") |
| Industry / business type | From `industry/<type>.md` template (auto-detected) |

## Process

1. **Confirm or discover competitors.** If user named them, use those. Otherwise
   delegate to backlink/keyword data layer to fetch top organic competitors by
   keyword overlap.
2. **Pull keyword gaps.** Keywords where competitors rank in top 10 but target
   doesn't rank, or ranks below #20.
3. **Pull top competitor pages.** Pages on competitor domains driving the most
   organic traffic, especially those of types target lacks (comparison pages,
   how-to guides, alternatives pages, glossary, etc.).
4. **Score opportunities by:**
   - Search volume × estimated CTR for target rank position
   - Keyword difficulty (KD) — lower is faster to win
   - Existing content match — partial coverage = quick fix vs new page
   - Industry relevance — gut-check against `industry/<type>.md`
5. **Output prioritized list:** ≤20 opportunities ordered by `impact / effort`.

## Output format

For each opportunity:

```
[priority] [keyword / topic]
  vol: <monthly searches>  KD: <0-100>  intent: <info|nav|trans|comm>
  target rank: <position or "not ranking">
  competitor ranks: <competitor1: pos, competitor2: pos>
  page type: <new | optimize existing | rewrite>
  est traffic gain: <range>
  why: <one-line rationale>
  next step: <concrete action>
```

Final summary table:

| # | Keyword | Vol | KD | Type | Effort | Est. gain |
|---|---|---|---|---|---|---|

## Competitor discovery (if not user-supplied)

Use the backlink/keyword data layer (L3, `integrations/ahrefs.md`):

1. `site_explorer.organic_competitors(target_domain)` — top 5 by keyword overlap
2. Filter to same industry (drop generic giants like wikipedia, reddit unless
   relevant)
3. Confirm with user before deep dive: "I see your competitors are X, Y, Z.
   Confirm or override?"

## Quality gates (do NOT recommend)

- Keywords with KD > 80 unless target has DR ≥ competitor DR
- Topics where target's existing content already ranks #1-3 (no upside)
- Branded keyword competitors (e.g. "X login" — pure brand defense, no growth)
- Topics outside target's domain expertise (E-E-A-T risk)
- Programmatic SEO at scale unless `industry/<type>.md` permits AND quality
  gates from `references/quality-gates.md` are met

## What this skill does NOT do

- Does not write the actual content — just identifies what to write
- Does not estimate exact rank positions after launch (no model can)
- Does not replace human editorial judgment on brand voice and positioning

## Integration with other modules

- After `audit` → call `growth` for next-step planning
- Before `competitor-pages` → use `growth` output to pick which competitors
  to target with comparison pages
- Pairs with `programmatic.md` if opportunity volume is in long-tail
  templates rather than individual pages

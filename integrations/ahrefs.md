# Backlink & keyword data integration (Ahrefs MCP)

Layer L3 — external API access for backlink, keyword, and traffic data.

## When this layer activates

- `growth-finder` agent needs competitor keyword overlap, gap analysis, top
  pages by traffic
- `audit` orchestrator wants to enrich findings with traffic context
  ("low-quality alt text on a page that drives 12k visits/mo" is more urgent
  than the same on a page driving 3 visits/mo)
- User asks for backlink profile, referring domains, or organic traffic
  trends

## Tool availability

The Ahrefs MCP exposes ~100 tools when authenticated. Probe at runtime:

1. Look for tools with prefix `site-explorer-*`, `keywords-explorer-*`,
   `rank-tracker-*`, `brand-radar-*`, `gsc-*`.
2. If none surfaced, fall back to L0 reasoning and label findings as
   `confidence:hypothesis`.

## Common operations

### Discover top competitors

```
site-explorer-organic-competitors(target=<domain>, country="US", limit=10)
```

Filter the result: drop reddit/wikipedia/youtube unless industry-relevant.

### Keyword gap (where competitors rank, target doesn't)

```
site-explorer-organic-keywords(target=<domain>, country="US")
site-explorer-organic-keywords(target=<competitor>, country="US")
```

Diff: keywords where competitor rank ≤ 10 AND target rank > 20 or absent.

### Top competitor pages by traffic

```
site-explorer-top-pages(target=<competitor>, country="US", limit=30)
```

Use to find content types target is missing (comparison, alternatives,
how-to, glossary, listicle).

### Backlink profile snapshot

```
site-explorer-domain-rating(target=<domain>)
site-explorer-backlinks-stats(target=<domain>)
site-explorer-referring-domains(target=<domain>, limit=50)
```

### Search Console keyword performance (if connected)

```
gsc-keywords(target=<domain>, period="last_28_days")
gsc-pages(target=<domain>, period="last_28_days")
gsc-page-history(url=<url>, period="last_3_months")
```

## Project setup

If a project ID is required (`management-projects` tool), discover it once
per workspace and reuse. Project IDs are workspace-scoped, do not commit
them to source.

## Rate limit / quota awareness

External APIs have query budgets. Before deep analysis:

1. Check current quota via `subscription-info-limits-and-usage` if available
2. Cache pulled data per session in `tests/private-fixtures/` (gitignored)
3. Avoid re-pulling identical queries within a session

## Confidence mapping

| Source | Confidence label |
|---|---|
| Direct API call returned data | Confirmed |
| API + reasoning to classify (e.g. page type from URL pattern) | Likely |
| Reasoning only (API unavailable / out of quota) | Hypothesis |

Always include the confidence label in any finding sourced from this layer.

## Privacy

- Never include API project IDs, domain rating numbers, or traffic estimates
  for non-target domains in artifacts that may be shared publicly
- Calibration runs against private domains stay in
  `tests/private-fixtures/` (gitignored)

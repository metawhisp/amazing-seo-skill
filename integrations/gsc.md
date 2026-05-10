# Google Search Console integration

Layer L3 — first-party search performance data.

## When this layer activates

- Audit needs traffic context to prioritize findings (high-traffic pages
  with issues > low-traffic pages with issues)
- User asks "what's actually working" — only GSC tells the truth on real
  queries and CTRs
- Investigating a ranking drop or traffic spike
- Validating content gap output from `growth-finder` against actual queries
  the site already gets impressions for

## What GSC gives that other layers do not

| Question | GSC layer | Other layers |
|---|---|---|
| Which queries actually bring impressions? | Yes | No |
| Real CTR by query / page | Yes | Estimated |
| Position changes over time | Yes (90 days) | No |
| Index coverage status | Yes | Partial via deep-audit |
| Mobile usability errors at scale | Yes | Single-page only via deep-audit |

## Common operations (via Ahrefs Brand Radar / GSC integration tools)

### Top queries with impressions but low CTR

Pages with high impressions and CTR < 3% are quick wins — often title/meta
issues, not ranking issues.

```
gsc-keywords(target=<domain>, period="last_28_days", min_impressions=100)
```

Filter: `position < 10 AND ctr < 3%` → title/meta optimization candidates.

### Pages losing position

```
gsc-page-history(url=<url>, period="last_3_months")
```

Look for a position step-change → align with content modification dates,
algorithm updates, or competitor content launches.

### Anonymized queries (the `(other)` bucket)

Some queries are hidden by Google. Use:

```
gsc-anonymous-queries(target=<domain>, period="last_28_days")
```

This bucket is often 30-50% of total impressions and reveals long-tail
opportunity invisible to keyword tools.

### Mobile vs desktop performance

```
gsc-performance-by-device(target=<domain>, period="last_28_days")
```

Big gap = mobile UX issues, INP problems, or geographic skew.

### Country breakdown

```
gsc-metrics-by-country(target=<domain>, period="last_28_days")
```

If non-target country has high impressions, hreflang or localized content
opportunity exists.

## Setup requirements

- GSC property must be verified (Domain or URL prefix)
- Ahrefs workspace connected to the GSC property
- User confirms which property to query when multiple are linked

## Confidence

GSC data is **first-party ground truth** — always `confidence:Confirmed`.
The only caveat: GSC has 2-3 day reporting lag. For "last 24 hours" needs,
GSC will not have data.

## Privacy

GSC data is sensitive (real queries users typed). Treat as confidential:

- Never include exact query strings from GSC in publicly committed files
- Aggregate / anonymize for any output that may be shared
- Calibration data stays in `tests/private-fixtures/` (gitignored)

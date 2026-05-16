<!-- Updated: 2026-05-16 -->
# Severity Rubric — single source of truth

Every finding emitted by any checker must carry one of three severity
labels. This document defines what each means and lists the criteria
per checker, so users and the orchestrator (`page_score.py`) agree on
priority without inference.

## Severity → Priority mapping

| Severity | Priority | Definition | Score deduction in page_score |
|----------|----------|------------|--------------------------------|
| **P0** | Critical | Blocks indexing, triggers a penalty, defeats a security control, or causes a non-deterministic outcome in Google's pipeline. **Fix immediately.** | −10 per finding |
| **P1** | High | Significantly impacts rankings, AI citation rate, or user experience for a measurable fraction of visitors. **Fix within 1 week.** | −5 per finding |
| **P2** | Medium | Optimization opportunity — site works, but not at full strength. **Fix within 1 month.** | −2 per finding |

The Critical/High/Medium/Low vocabulary used in reports maps:
- `P0` → "Critical"
- `P1` → "High"
- `P2` → "Medium"
- (no `P3` — "Low" findings shouldn't be emitted; they're noise)

## What P0 means concretely

Use **P0** if any of these apply:

- **Blocks indexing.** `noindex` on production page that should rank.
  `robots.txt` Disallow on a high-value path. Canonical points away.
- **Causes penalty.** Cloaking detected. Doorway pages. Thin auto-gen content at scale.
- **Defeats security control.** CSP allows `'unsafe-inline'` without nonce
  (defeats XSS). HSTS missing on HTTPS-required path.
- **Non-deterministic outcome.** Canonical differs raw HTML vs JS-rendered
  (per Google Dec 2025 JS SEO docs, Google may pick either). Schema only in
  rendered HTML (AI crawlers see none).
- **Breaks rich result eligibility.** Required schema field missing.
- **Hreflang set ignored.** Missing self-reference invalidates the whole hreflang set.

## What P1 means concretely

- Missing critical SEO element (title, H1, canonical, meta description).
- Recommended schema field missing (rich result still works but degraded).
- HSTS too short / missing `includeSubDomains`.
- 5xx errors on Googlebot-served pages.
- 3+ redirect hops on indexed URLs.
- Below-fold images missing `loading="lazy"` (LCP/INP regression).
- ≥3 images without `width`/`height` (CLS risk).
- Content under page-type word minimum.
- Below ≥70% next-gen image format (WebP/AVIF).
- Mixed content on HTTPS page.
- Hreflang missing x-default.

## What P2 means concretely

- Missing optional security header (Referrer-Policy, Permissions-Policy).
- `X-Content-Type-Options` not `nosniff` (security best-practice, not a Google signal).
- CSP report-only when ready to enforce.
- Auth-gated outbound links (401/403) — soft signal, manual verify.
- Stale `lastmod` in sitemap.
- Slightly long avg sentence length (22-30 words; 30+ is P1).
- 1-2 broken links on a 50-link page.

## Standardized JSON output (v0.7.0+)

Every checker emits findings as **structured dicts**, not bare strings:

```json
{
  "issues": [
    {
      "severity": "P0",
      "text": "CSP allows 'unsafe-inline' without nonce/hash — defeats XSS protection",
      "evidence": {
        "csp_directive": "default-src 'self' 'unsafe-inline'",
        "missing": "nonce"
      }
    },
    {
      "severity": "P1",
      "text": "HSTS max-age too short (3600s; recommend >= 31536000s)",
      "evidence": {"current_max_age": 3600, "recommended_min": 31536000}
    }
  ]
}
```

The `evidence` field is optional but encouraged — surfaces in dashboard
run-detail page for drill-down.

## Migration roadmap

`page_score.py` accepts BOTH formats during the migration window:
1. **Legacy (`v0.6.x` and earlier)**: `issues: ["text", "text", ...]` —
   severity inferred via regex patterns in `page_score._classify_severity`.
   Brittle: silently fails to P2 if a checker rewords its message.
2. **Envelope (`v0.7.0+`)**: `issues: [{severity, text, evidence?}, ...]` —
   severity travels with the finding. Authoritative.

Migration status (as of v0.7.0):

| Checker | Status |
|---------|--------|
| `security_headers_checker.py` | ✓ migrated (reference impl) |
| `redirect_chain_checker.py`   | legacy — pending v0.7.1 |
| `broken_links_checker.py`     | legacy — pending v0.7.1 |
| `images_audit.py`             | legacy — pending v0.7.1 |
| `schema_recommended_fields.py`| legacy — pending v0.7.1 |
| `content_quality.py`          | legacy — pending v0.7.1 |
| `hreflang_checker.py`         | legacy — pending v0.7.1 |
| `llms_txt_checker.py`         | legacy — pending v0.7.1 |
| `robots_checker.py`           | legacy — pending v0.7.2 |
| `sitemap_validator.py`        | legacy — pending v0.7.2 |
| `local_seo_checker.py`        | legacy — pending v0.7.2 |
| `internal_link_graph.py`      | legacy — pending v0.7.2 |
| (other checkers)              | informational, no issues list |

Migration of any checker requires:
1. Import `finding` and `result_envelope` from `_fetch`.
2. Replace `issues.append("text")` with `issues.append(finding("PX", "text", {evidence}))`.
3. Replace final dict construction with `out = result_envelope(target, response, "this_checker.py", **payload)`.

See `security_headers_checker.py` for the reference implementation.

## How `page_score.py` handles severity

```
for each issue in checker's issues list:
    if isinstance(issue, dict) and "severity" in issue:
        # New format — use severity directly (authoritative)
        sev = issue["severity"]
        text = issue["text"]
        evidence = issue.get("evidence")
    else:
        # Legacy string — regex classifier (deprecated path)
        sev = regex_classify(issue)
        text = issue
```

Both paths emit the same final shape into the aggregated `all_findings`
list. The dashboard, history, and HTML reports don't need to know which
path produced the finding.

## When a checker shouldn't emit `issues`

Some checkers are **informational** — they produce data, not verdicts:

- `cms_detector.py` — detects platform, no judgment
- `parse_html.py` — extracts HTML elements
- `fetch_page.py` — fetches and saves
- `internal_link_graph.py` — produces a graph (orphans are findings though)
- `log_analyzer.py` — aggregates server logs

These checkers do NOT need to emit `issues`. They may emit `summary` or
similar fields. `page_score.py` weights them at 0 (informational only).

## Anti-patterns

❌ **Don't** emit P3 / P4 / "Info" / "Notice" — only P0/P1/P2.
❌ **Don't** use severity to gate scoring weight — weight is per-checker
   in `page_score.py:CHECKERS`, not per-finding.
❌ **Don't** add "severity escalation" logic (e.g. "P2 → P1 if count > 5").
   If a metric is critical above some threshold, emit P1 directly when the
   threshold is crossed.
❌ **Don't** mix severities in a single finding's `text`. One issue = one
   severity. Multiple = multiple findings.

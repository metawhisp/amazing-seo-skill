# Onboarding — amazing-seo-skill

Reference for first-time setup. The interactive `tools/onboarding.sh`
script will probe your machine and tell you what's missing; this doc
explains **what each piece does** and **why you'd add it**.

> **TL;DR** — after `git clone`, run `./install.sh` (or set up `.venv`
> manually), then `./tools/onboarding.sh`. The wizard reports active
> layers and shows the next-step commands tailored to your machine.

---

## Two ways to run

The skill works at any of two installation depths:

| Mode | What works | What you need |
|------|------------|---------------|
| **Lightweight** | Everything reasoning-based (L0): audits, scoring, recommendations, schema generation, GEO advice, plan creation. WebFetch covers content retrieval. | Just `git clone` into `~/.claude/skills/amazing-seo-skill`. **Zero setup.** |
| **Full** | All 4 layers: deterministic Python checkers (L1), real-browser CWV + 251-rule deep audit (L2), Ahrefs/GSC via MCP (L3), 5-LLM citation ensemble (L4). | Run `./install.sh`, then add API keys per below. |

In Claude Code, just say `audit https://example.com` and the skill picks
up automatically via its trigger keywords. The orchestrator detects what's
available and uses the best layer it can.

---

## Capability layers — what each one unlocks

### L0 — Claude reasoning + WebFetch (always on)

Always available. Claude reads the live page via WebFetch, reasons about
on-page SEO, schema, structure, GEO signals. **Findings are labelled
"Hypothesis"** because they're reasoning-only.

### L1 — Deterministic Python checkers

11 standalone scripts in `scripts/`. Each fetches the target with a
realistic Chrome User-Agent (passes Cloudflare/WAFs), runs SSRF guards
against private IPs, retries on 5xx, and outputs JSON with a meaningful
exit code (0 = clean, 1 = fetch failed, 2 = issues found). **Findings
labelled "Confirmed"** because they're data-backed.

| Script | What it verifies |
|--------|------------------|
| `robots_checker.py` | robots.txt structure, per-bot Allow/Disallow for 20 crawlers, sitemap refs, typos |
| `sitemap_validator.py` | XML validity, sitemap-index recursion, 50k URL / 50 MiB limits, HTTPS-only, lastmod sanity, deprecated `<priority>`/`<changefreq>`, sample HTTP-200 check, robots cross-ref |
| `redirect_chain_checker.py` | Per-hop trace, HTTP→HTTPS upgrade, 301/302 mix, loop detection, canonical alignment |
| `security_headers_checker.py` | HSTS, CSP (unsafe-inline / nonce), X-Frame-Options or CSP frame-ancestors, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, mixed-content scan |
| `broken_links_checker.py` | Per-page link audit: `<a>`/`<link>`/`<script>`/`<img>`/`<source>`/`<iframe>` + CSS bg, concurrent HEAD, splits 4xx vs 5xx vs auth-gated 401/403 |
| `images_audit.py` | Alt coverage, format mix (WebP/AVIF/JPEG/PNG/SVG) vs ≥70% next-gen target, width/height for CLS, lazy on below-fold, size flags ≥200KB/≥500KB |
| `hreflang_checker.py` | BCP-47 codes, x-default, self-reference, reciprocity (parallel) |
| `schema_recommended_fields.py` | Per-schema-item required vs recommended field coverage, 0-100 completeness |
| `llms_txt_checker.py` | llms.txt structure + link-validity (HEAD probe of referenced URLs) |
| `internal_link_graph.py` | Crawl-built adjacency: true orphans, sitemap gaps, depth-4+ pages, hub pages, dead-ends |
| `psi_checker.py` | PageSpeed Insights API: CrUX field 75th-pct LCP/INP/CLS/FCP/TTFB + Lighthouse lab |
| `aeo_gemini.py` | Gemini + Google Search grounding probe (Google AI Overviews proxy) |
| `parse_html.py` | Extract title/meta/headings/canonical/hreflang/images/links/schema from saved HTML |
| `fetch_page.py` | Standalone fetcher with SSRF guard; saves HTML to disk for offline analysis |
| `amazing_crawl.py` | Open-source async crawler — SF alternative when SF isn't installed or you exceed the 500-URL free tier. Captures status/title/meta/canonical/H1/schema/links per URL into SQLite, resumes from checkpoint, exports CSV/JSON |
| `page_score.py` | **All-in-one orchestrator** — runs every checker above in parallel, aggregates to 0-100 Health Score with prioritized findings |

**Requires:** `./install.sh` (or manual `.venv` setup with
`pip install -r requirements.txt`).

### L2 — Local engines (heavy lifting)

Two CLIs invoked via `.bin/` wrappers:

- **deep-audit engine** — 251-rule deterministic audit + real-browser Core
  Web Vitals via Playwright Chromium. Returns aggregated category scores.
- **AEO-citations engine** — invokes 4 LLM providers (Anthropic, OpenAI,
  Perplexity, xAI) with your target queries, reports per-provider citation
  status.

These are **engine-agnostic**: you set `DEEP_AUDIT_ENGINE_PKG` and
`AEO_CITATIONS_ENGINE_PKG_SPEC` env vars before running `./install.sh`,
and `.bin/.engines.env` is generated locally. The repo ships no engine
identifiers, so you can swap implementations freely.

**Requires:** `./install.sh` with the engine env vars set.

### L3 — Ahrefs MCP / Google Search Console (external APIs)

Enables backlink, keyword, traffic, and search-performance enrichment.
Not configured here — connect via Claude Code's MCP system. When
connected, the orchestrator detects available tools at runtime and uses
them for the `growth` and `audit` workflows.

### L4 — Multi-LLM citation ensemble

5 providers, queried in parallel during AEO checks. Each measures
"does this LLM cite our domain when answering [query]?"

| Provider | Keychain entry / env var | What it covers |
|----------|--------------------------|----------------|
| Anthropic (Claude) | `anthropic-api-key` / `ANTHROPIC_API_KEY` | Claude AI |
| OpenAI (ChatGPT) | `openai-api-key` / `OPENAI_API_KEY` | ChatGPT |
| Perplexity | `perplexity-api-key` / `PERPLEXITY_API_KEY` | Perplexity AI |
| xAI (Grok) | `x.ai-api-key` / `XAI_API_KEY` | Grok |
| Google Gemini | `google-gemini-api-key` / `GOOGLE_GEMINI_API_KEY` | Gemini + Google Search grounding → **Google AI Overviews / AI Mode proxy** |

PSI is its own key (separate from L4 ensemble):

| Tool | Keychain entry / env var | What it does |
|------|--------------------------|--------------|
| PageSpeed Insights | `google-psi-api-key` / `GOOGLE_PSI_API_KEY` | Real CrUX/Lighthouse CWV. Keyless gets ~25 req/day; with a (free) key, ~25,000 req/day. |

### Adding keys (macOS)

```bash
security add-generic-password -s anthropic-api-key      -a $USER -w
security add-generic-password -s openai-api-key         -a $USER -w
security add-generic-password -s perplexity-api-key     -a $USER -w
security add-generic-password -s x.ai-api-key           -a $USER -w
security add-generic-password -s google-gemini-api-key  -a $USER -w
security add-generic-password -s google-psi-api-key     -a $USER -w
```

You'll be prompted for the secret on each line. Keys are never written
to disk by this skill — they're read from Keychain at runtime.

### Adding keys (Linux / WSL / non-macOS)

Use environment variables instead. Add to your shell rc:

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export PERPLEXITY_API_KEY=...
export XAI_API_KEY=...
export GOOGLE_GEMINI_API_KEY=...
export GOOGLE_PSI_API_KEY=...
```

---

## How findings are labelled

Each finding in a report carries a **confidence label** that tells you
which layer produced it:

- **Confirmed** — deterministic check (L1) or real-browser measurement (L2)
- **Likely** — reasoning (L0) supported by at least one external signal
- **Hypothesis** — reasoning alone, no data backing

Use this to prioritise. Critical-severity Confirmed findings should be
acted on first; Hypothesis findings are starting points for further
verification, not conclusions.

---

## Common first-run questions

**Q: It blocks me on Cloudflare-protected sites.**
A: That's why we ship a realistic Chrome UA in `scripts/_fetch.py`. If
you still hit 403/429, override with `AMAZING_SEO_UA="<your UA>"` env var,
or fall back to browser-based fetching via Claude Code's MCP browsers.

**Q: PSI returns 429 quota exceeded.**
A: You're keyless (25 req/day shared pool). Add `google-psi-api-key` —
it's free at <https://developers.google.com/speed/docs/insights/v5/get-started>.

**Q: Gemini probe returns "key not found".**
A: Add `google-gemini-api-key`. Get one free at
<https://aistudio.google.com/apikey>. With Google Search grounding enabled
(this skill does it automatically), each query consumes ~1 grounding unit.

**Q: How do I run a quick smoke test?**
A: `./tools/onboarding.sh` — it probes everything and tells you what's
active. Repeat any time.

**Q: I run on Linux, no Keychain.**
A: Use env vars (see "Adding keys (Linux)" above). The skill checks env
first, then Keychain, so env-only setups work fully.

**Q: Can I use a different deep-audit engine?**
A: Yes — engines are pluggable. Set `DEEP_AUDIT_ENGINE_PKG` (npm package
name) and `DEEP_AUDIT_ENGINE_BIN_NAME` (binary name) before running
`./install.sh`. Same for `AEO_CITATIONS_ENGINE_PKG_SPEC` (pip spec). The
shim in `.bin/` wraps whatever you supply.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `_fetch.py` returns garbage HTML | Server sends Brotli-compressed body, requests can't decode | Already fixed: we advertise only `gzip, deflate` by default. If your server forces brotli, `pip install brotli` and add it to `_BASE_HEADERS["Accept-Encoding"]` |
| `parse_html.py` parses oddly | lxml not installed → falls back to html.parser | `.venv/bin/pip install lxml` |
| `psi_checker.py` always 429 | No API key, sharing the keyless pool | Add `google-psi-api-key` |
| `aeo-citations.sh` warns about missing keys | One or more L4 providers not configured | Add keys for the surfaces you care about; skipping providers is OK, output marks them as not-probed |
| `internal_link_graph.py` shows 90% orphans | `--max-pages` too low — most sitemap URLs not crawled | Increase `--max-pages` (default 200; aim for ≥ sitemap size) |
| `sitemap_validator.py` says "not referenced in robots" but it is | Apex vs www mismatch: you passed `example.com`, robots.txt declares `https://www.example.com/sitemap.xml` | Pass the canonical host explicitly: `sitemap_validator.py https://www.example.com/sitemap.xml` |
| Hook example in settings.json doesn't fire | Old `~/.claude/skills/seo/...` path | Update to `~/.claude/skills/amazing-seo-skill/...` — see `hooks/validate-schema.py` and `hooks/pre-commit-seo-check.sh` headers |
| `internal_link_graph.py` takes minutes on a big site | Sequential crawl with 0.3s polite delay | Tune `--delay 0` and `--max-pages` for speed; or use Screaming Frog (faster, separate skill) |
| `aeo_gemini.py` returns no citations | Either no L4 key, OR query is too generic and grounding didn't fire | Add `google-gemini-api-key`; pick more specific queries that include domain-relevant keywords |
| `install.sh` syntax error on bash 3.2 | Apple ships old bash 3.2; heredoc parser false-positives | Run with `/opt/homebrew/bin/bash` or just trust the script — it executes correctly |

---

## Privacy

- No API key is ever written to disk by this skill.
- Calibration data and per-domain test runs go in `tests/private-fixtures/`
  (gitignored — never pushed).
- Engine config (`.bin/.engines.env`) is generated locally and gitignored —
  the public repo never references any specific engine package.

---

## Next

Once `./tools/onboarding.sh` shows green across L0-L4, try:

```
audit https://example.com           # full site
page https://example.com/post       # single page deep-dive
technical https://example.com       # technical SEO only
geo https://example.com             # AI Overviews readiness
aeo example.com "best email tool"   # live LLM citation check (needs L4 keys)
growth example.com                  # competitor gap (needs L3 / Ahrefs MCP)
```

See [SKILL.md](SKILL.md) for the full command reference.

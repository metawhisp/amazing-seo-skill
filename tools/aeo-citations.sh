#!/usr/bin/env bash
# Live AEO citation check — query 4 LLM providers and report which mention the
# target domain. Reads API keys from macOS Keychain (no env files committed).
#
# The AEO citations engine expects a TOML config file at a specific name in the
# working directory. That filename is supplied by .bin/.engines.env (generated
# by install.sh) so this script stays decoupled from the upstream engine name.
#
# Usage:
#   tools/aeo-citations.sh <domain> "<query1>" "<query2>" ...
#
# Example:
#   tools/aeo-citations.sh example.com "best email tool" "alternatives to X"
set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILL_DIR"

[ -f .bin/.engines.env ] && source .bin/.engines.env

: "${AMAZING_SEO_AEO_CITATIONS_ENGINE:?engine binary not configured — run install.sh}"
: "${AMAZING_SEO_AEO_CITATIONS_CONFIG_FILENAME:?engine config filename not set in .bin/.engines.env}"

if [ $# -lt 2 ]; then
  echo "Usage: $0 <domain> \"<query1>\" [\"<query2>\" ...]" >&2
  exit 1
fi

DOMAIN="$1"; shift
QUERIES=("$@")

# ── Pull keys from Keychain (no caching, no env files) ─────────────────────
get_key() {
  security find-generic-password -s "$1" -w 2>/dev/null || echo ""
}

OPENAI_API_KEY=$(get_key openai-api-key)
ANTHROPIC_API_KEY=$(get_key anthropic-api-key)
PERPLEXITY_API_KEY=$(get_key perplexity-api-key)
XAI_API_KEY=$(get_key x.ai-api-key)
GOOGLE_GEMINI_API_KEY=$(get_key google-gemini-api-key)

[ -z "$OPENAI_API_KEY" ]        && echo "WARN: openai-api-key missing in Keychain"        >&2
[ -z "$ANTHROPIC_API_KEY" ]     && echo "WARN: anthropic-api-key missing in Keychain"     >&2
[ -z "$PERPLEXITY_API_KEY" ]    && echo "WARN: perplexity-api-key missing in Keychain"    >&2
[ -z "$XAI_API_KEY" ]           && echo "WARN: x.ai-api-key missing in Keychain"          >&2
[ -z "$GOOGLE_GEMINI_API_KEY" ] && echo "WARN: google-gemini-api-key missing in Keychain (Gemini probe disabled)" >&2

# ── Write minimal engine config (gitignored fixtures dir) ──────────────────
RUN_DIR="$SKILL_DIR/tests/private-fixtures/aeo-runs/$DOMAIN"
mkdir -p "$RUN_DIR"
CONFIG="$RUN_DIR/$AMAZING_SEO_AEO_CITATIONS_CONFIG_FILENAME"

{
  echo "domain = \"$DOMAIN\""
  echo ""
  echo "ai_queries = ["
  for q in "${QUERIES[@]}"; do
    escaped=$(printf '%s' "$q" | sed 's/\\/\\\\/g; s/"/\\"/g')
    echo "  \"$escaped\","
  done
  echo "]"
} > "$CONFIG"

# ── Run AEO check across all 4 baseline providers ──────────────────────────
export OPENAI_API_KEY ANTHROPIC_API_KEY PERPLEXITY_API_KEY XAI_API_KEY

cd "$RUN_DIR"
echo "==> AEO citation check for $DOMAIN"
echo "    queries:   ${#QUERIES[@]}"
echo "    config:    $CONFIG"
echo "    providers: openai, anthropic, perplexity, xai"
echo "    + gemini (Google AI Overviews proxy) if key available"
echo ""

OUT="$RUN_DIR/results.txt"
"$AMAZING_SEO_AEO_CITATIONS_ENGINE" ai 2>&1 | tee "$OUT"

# ── Fifth provider: Gemini with google_search grounding ────────────────────
# Approximates Google AI Overviews / AI Mode behaviour. The engine above
# doesn't (currently) cover Gemini; we run our own probe alongside.
GEMINI_OUT="$RUN_DIR/gemini.json"
if [ -n "$GOOGLE_GEMINI_API_KEY" ]; then
  echo ""
  echo "==> Gemini probe (google_search grounding) — Google AI Overviews proxy"
  export GOOGLE_GEMINI_API_KEY
  "$SKILL_DIR/.venv/bin/python" "$SKILL_DIR/scripts/aeo_gemini.py" \
    "$DOMAIN" "${QUERIES[@]}" --json > "$GEMINI_OUT" 2>"$RUN_DIR/gemini.err"
  GEMINI_EXIT=$?
  if [ "$GEMINI_EXIT" -eq 0 ] || [ "$GEMINI_EXIT" -eq 2 ]; then
    CITED=$("$SKILL_DIR/.venv/bin/python" -c "
import json, sys
d = json.load(open('$GEMINI_OUT'))
print(f\"{d.get('queries_cited',0)}/{d.get('queries_total',0)} queries cited ({d.get('citation_rate',0)*100:.0f}%)\")
")
    echo "    Gemini: $CITED → $GEMINI_OUT"
  else
    echo "    Gemini probe failed (exit $GEMINI_EXIT); see $RUN_DIR/gemini.err"
  fi
else
  echo ""
  echo "==> Skipping Gemini probe (no google-gemini-api-key in Keychain)"
fi

echo ""
echo "==> Summary saved: $OUT (4-provider engine) + $GEMINI_OUT (Gemini)"

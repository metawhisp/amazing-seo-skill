#!/usr/bin/env bash
# Live AEO citation check — query 4 LLM providers and report which mention the
# target domain. Reads API keys from macOS Keychain (no env files committed).
#
# Usage:
#   tools/aeo-citations.sh <domain> "<query1>" "<query2>" ...
#
# Example:
#   tools/aeo-citations.sh example.com "best email tool" "alternatives to X"
set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILL_DIR"

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

[ -z "$OPENAI_API_KEY" ]     && echo "WARN: openai-api-key missing in Keychain"     >&2
[ -z "$ANTHROPIC_API_KEY" ]  && echo "WARN: anthropic-api-key missing in Keychain"  >&2
[ -z "$PERPLEXITY_API_KEY" ] && echo "WARN: perplexity-api-key missing in Keychain" >&2
[ -z "$XAI_API_KEY" ]        && echo "WARN: x.ai-api-key missing in Keychain"       >&2

# ── Write minimal local config (gitignored fixtures dir) ───────────────────
RUN_DIR="$SKILL_DIR/tests/private-fixtures/aeo-runs/$DOMAIN"
mkdir -p "$RUN_DIR"
CONFIG="$RUN_DIR/.searchstack.toml"

{
  echo "domain = \"$DOMAIN\""
  echo ""
  echo "ai_queries = ["
  for q in "${QUERIES[@]}"; do
    # Escape backslashes and double quotes for TOML
    escaped=$(printf '%s' "$q" | sed 's/\\/\\\\/g; s/"/\\"/g')
    echo "  \"$escaped\","
  done
  echo "]"
} > "$CONFIG"

# ── Run AEO check across all 4 providers ───────────────────────────────────
export OPENAI_API_KEY ANTHROPIC_API_KEY PERPLEXITY_API_KEY
# searchstack also recognizes XAI_API_KEY indirectly via grok provider config
export XAI_API_KEY

cd "$RUN_DIR"
echo "==> AEO citation check for $DOMAIN"
echo "    queries: ${#QUERIES[@]}"
echo "    config:  $CONFIG"
echo ""

OUT="$RUN_DIR/results.txt"
"$SKILL_DIR/.bin/_engine_aeo_citations" ai 2>&1 | tee "$OUT"

echo ""
echo "==> Summary saved: $OUT"

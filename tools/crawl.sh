#!/usr/bin/env bash
# Smart crawler dispatcher.
#
# Decides between Screaming Frog CLI (if installed & user has license)
# and amazing-crawl (our async Python crawler) automatically.
#
# Selection logic:
#   1. If --force-amazing → always use amazing-crawl
#   2. If --force-sf → always use Screaming Frog (fails if not installed)
#   3. Auto:
#      - SF binary found AND requested URLs ≤ 500 → use SF (better data
#        quality, parallel JS rendering, well-known CSV exports)
#      - SF not found OR requested URLs > 500 → use amazing-crawl
#        (free, unlimited, async, no GUI required)
#
# Usage:
#   tools/crawl.sh <url> [--max-pages N] [--js] [--csv FILE] [--force-amazing|--force-sf]
#
# Examples:
#   tools/crawl.sh https://example.com --max-pages 5000
#   tools/crawl.sh https://example.com --max-pages 50000 --csv export.csv
#   tools/crawl.sh https://example.com --force-amazing --js

set -u

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILL_DIR"

PY="$SKILL_DIR/.venv/bin/python"
SF="/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher"

URL=""
MAX_PAGES=10000
JS_FLAG=""
CSV=""
JSON=""
OUTPUT=""
FORCE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --max-pages)       MAX_PAGES="$2"; shift 2 ;;
    --js)              JS_FLAG="--js"; shift ;;
    --csv)             CSV="$2"; shift 2 ;;
    --json)            JSON="$2"; shift 2 ;;
    --output)          OUTPUT="$2"; shift 2 ;;
    --force-amazing)   FORCE="amazing"; shift ;;
    --force-sf)        FORCE="sf"; shift ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) URL="$1"; shift ;;
  esac
done

if [ -z "$URL" ]; then
  echo "Usage: tools/crawl.sh <url> [--max-pages N] [--js] [--csv FILE] [--force-amazing|--force-sf]" >&2
  exit 1
fi

# ── Selection ─────────────────────────────────────────────────────────────
SF_AVAILABLE="no"
if [ -x "$SF" ]; then SF_AVAILABLE="yes"; fi

case "$FORCE" in
  amazing) CRAWLER="amazing" ;;
  sf)
    if [ "$SF_AVAILABLE" != "yes" ]; then
      echo "ERROR: --force-sf but Screaming Frog not found at $SF" >&2
      exit 1
    fi
    CRAWLER="sf" ;;
  *)
    # Auto: prefer SF if installed AND within free tier; else amazing-crawl
    if [ "$SF_AVAILABLE" = "yes" ] && [ "$MAX_PAGES" -le 500 ]; then
      CRAWLER="sf"
    else
      CRAWLER="amazing"
    fi ;;
esac

echo "==> Crawler selected: $CRAWLER" >&2
if [ "$CRAWLER" = "sf" ]; then
  echo "    Reason: Screaming Frog detected and max_pages=$MAX_PAGES within free tier" >&2
else
  if [ "$SF_AVAILABLE" = "yes" ]; then
    echo "    Reason: max_pages=$MAX_PAGES exceeds Screaming Frog free-tier 500 — using amazing-crawl" >&2
  else
    echo "    Reason: Screaming Frog not installed — using amazing-crawl" >&2
    echo "            (free, unlimited URLs, async — drop-in fallback)" >&2
  fi
fi
echo "" >&2

# ── Run ───────────────────────────────────────────────────────────────────
if [ "$CRAWLER" = "sf" ]; then
  DOMAIN=$(echo "$URL" | sed -E 's|^https?://||; s|/.*||')
  _OUTPUT_BASE="${AMAZING_SEO_OUTPUT_DIR:-$HOME/.amazing-seo-skill/runs}"
  OUT_DIR="${OUTPUT:-$_OUTPUT_BASE/sf-crawl-$DOMAIN-$(date -u +%Y%m%d-%H%M%S)}"
  mkdir -p "$OUT_DIR"
  timeout 600 "$SF" \
    --crawl "$URL" \
    --headless \
    --output-folder "$OUT_DIR" \
    --export-tabs "Internal:All,Response Codes:All,Page Titles:All,Page Titles:Duplicate,Meta Description:All,Meta Description:Missing,Meta Description:Duplicate,H1:All,H1:Duplicate,H1:Missing,H2:All,H2:Duplicate,Canonicals:All,Directives:All,Hreflang:All,Images:Missing Alt Text,Structured Data:All" \
    --overwrite 2>&1 | grep -E "SpiderProgress|Completed|Exporting|ERROR|FATAL"
  echo ""
  echo "==> SF results: $OUT_DIR" >&2
  exit 0
fi

# amazing-crawl
ARGS=("$URL" "--max-pages" "$MAX_PAGES")
[ -n "$JS_FLAG" ] && ARGS+=("$JS_FLAG")
[ -n "$CSV" ]    && ARGS+=("--csv" "$CSV")
[ -n "$JSON" ]   && ARGS+=("--json" "$JSON")
[ -n "$OUTPUT" ] && ARGS+=("--output" "$OUTPUT")
exec "$PY" scripts/amazing_crawl.py "${ARGS[@]}"

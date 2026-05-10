#!/usr/bin/env bash
# Multi-page deep audit driver — fetches a sitemap, picks N representative
# URLs, runs the deep-audit engine on each, aggregates scores, and surfaces
# pages that diverge from the site average.
#
# Usage:
#   tools/multi-page-audit.sh <domain_or_sitemap_url> [--limit N] [--out DIR]
#
# Defaults: --limit 20, --out tests/private-fixtures/multi-audit-<domain>/
set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILL_DIR"

TARGET=""
LIMIT=20
OUT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --out)   OUT="$2"; shift 2 ;;
    *)       TARGET="$1"; shift ;;
  esac
done

if [ -z "$TARGET" ]; then
  echo "Usage: $0 <domain_or_sitemap_url> [--limit N] [--out DIR]" >&2
  exit 1
fi

# Normalize: if domain only, append /sitemap.xml
case "$TARGET" in
  *sitemap*) SITEMAP_URL="$TARGET" ;;
  http*)     SITEMAP_URL="${TARGET%/}/sitemap.xml" ;;
  *)         SITEMAP_URL="https://${TARGET#//}/sitemap.xml" ;;
esac

DOMAIN=$(echo "$SITEMAP_URL" | sed -E 's|^https?://||; s|/.*||')
[ -z "$OUT" ] && OUT="tests/private-fixtures/multi-audit-$DOMAIN"
mkdir -p "$OUT"

echo "==> Fetching sitemap: $SITEMAP_URL"
curl -sf "$SITEMAP_URL" > "$OUT/sitemap.xml" || { echo "FAIL: cannot fetch sitemap" >&2; exit 1; }

# Extract <loc> entries; if it's an index, follow the first sub-sitemap
TOTAL=$(grep -c "<loc>" "$OUT/sitemap.xml" || echo 0)
echo "    sitemap entries: $TOTAL"

if grep -q "<sitemap>" "$OUT/sitemap.xml"; then
  echo "    detected sitemap index — following first sub-sitemap"
  SUB=$(grep -oE "<loc>[^<]+</loc>" "$OUT/sitemap.xml" | head -1 | sed 's|</\?loc>||g')
  curl -sf "$SUB" > "$OUT/sitemap.xml"
fi

# Sample URLs: take first $LIMIT (deterministic — caller can shuffle externally if needed)
# Two separate substitutions: macOS sed BRE doesn't support `\?` reliably.
grep -oE "<loc>[^<]+</loc>" "$OUT/sitemap.xml" \
  | sed -e 's|<loc>||' -e 's|</loc>||' \
  | head -"$LIMIT" > "$OUT/sample.txt"

SAMPLE_COUNT=$(wc -l < "$OUT/sample.txt" | tr -d ' ')
echo "==> Auditing $SAMPLE_COUNT pages (limit=$LIMIT)"

I=0
while read -r URL; do
  I=$((I + 1))
  SLUG=$(echo "$URL" | sed 's|https\?://||; s|[^a-zA-Z0-9]|_|g' | cut -c1-80)
  RESULT="$OUT/page-$(printf '%03d' "$I")-${SLUG}.json"
  echo "  [$I/$SAMPLE_COUNT] $URL"
  ./.bin/_engine_deep_audit audit "$URL" --format json > "$RESULT" 2>&1 || true
done < "$OUT/sample.txt"

echo ""
echo "==> Aggregating scores"
.venv/bin/python <<PY
import json, glob, statistics, os, sys
from pathlib import Path

results = sorted(Path("$OUT").glob("page-*.json"))
rows = []
for p in results:
    try:
        d = json.loads(p.read_text())
        rows.append({
            "url": d.get("url", "?"),
            "score": d.get("overallScore", 0),
            "categories": {c["categoryId"]: c["score"] for c in d.get("categoryResults", [])},
        })
    except Exception:
        continue

if not rows:
    print("No valid audit results")
    sys.exit(1)

scores = [r["score"] for r in rows]
avg = statistics.mean(scores)
stdev = statistics.stdev(scores) if len(scores) > 1 else 0
print(f"Pages audited:     {len(rows)}")
print(f"Average score:     {avg:.1f}")
print(f"Score stdev:       {stdev:.1f}")
print(f"Min / Max:         {min(scores)} / {max(scores)}")

# Outliers (>1 stdev below mean)
outliers = sorted([r for r in rows if r["score"] < avg - stdev], key=lambda r: r["score"])
print(f"\nUnderperformers (>1 stdev below mean):")
for r in outliers[:10]:
    print(f"  {r['score']:5.1f}  {r['url']}")

# Worst category aggregated
all_cats = set()
for r in rows: all_cats.update(r["categories"].keys())
print(f"\nAverage per category:")
cat_avgs = []
for c in sorted(all_cats):
    vals = [r["categories"].get(c, 0) for r in rows if c in r["categories"]]
    if vals:
        cat_avgs.append((c, statistics.mean(vals)))
for c, v in sorted(cat_avgs, key=lambda x: x[1])[:5]:
    print(f"  {v:5.1f}  {c}  (worst categories)")

summary = {
    "pages_audited": len(rows),
    "average_score": round(avg, 1),
    "stdev": round(stdev, 1),
    "min": min(scores),
    "max": max(scores),
    "underperformers": [{"url": r["url"], "score": r["score"]} for r in outliers],
    "category_averages": dict(cat_avgs),
    "per_page": rows,
}
Path("$OUT/SUMMARY.json").write_text(json.dumps(summary, indent=2))
print(f"\n==> Full summary: $OUT/SUMMARY.json")
PY

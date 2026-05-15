#!/usr/bin/env bash
# Site-level audit orchestrator.
#
# Pipeline:
#   1. Fetch the sitemap (auto-discover /sitemap.xml; follow sitemap index).
#   2. Sample N URLs (random or first-N).
#   3. Run page_score.py in parallel on each URL.
#   4. Aggregate per-page Health Scores into site-wide stats: mean, median,
#      stdev, distribution.
#   5. Identify under-performers (>1 stdev below the mean).
#   6. Emit a single Markdown report.
#
# Usage:
#   tools/site_audit.sh <domain_or_sitemap_url> [--limit N] [--out DIR] [--no-psi]
#
# Examples:
#   tools/site_audit.sh example.com --limit 20 > REPORT.md
#   tools/site_audit.sh https://example.com/sitemap.xml --limit 50
#
# Defaults: --limit 20, --out tests/private-fixtures/site-<domain>/

set -u

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILL_DIR"

PY="$SKILL_DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "ERROR: $PY not found. Run ./install.sh first." >&2
  exit 1
fi

TARGET=""
LIMIT=20
OUT=""
NO_PSI=""
WORKERS=4

while [ $# -gt 0 ]; do
  case "$1" in
    --limit)   LIMIT="$2"; shift 2 ;;
    --out)     OUT="$2"; shift 2 ;;
    --no-psi)  NO_PSI="--no-psi"; shift ;;
    --workers) WORKERS="$2"; shift 2 ;;
    *)         TARGET="$1"; shift ;;
  esac
done

if [ -z "$TARGET" ]; then
  echo "Usage: $0 <domain_or_sitemap_url> [--limit N] [--out DIR] [--no-psi]" >&2
  exit 1
fi

# Normalise sitemap URL
case "$TARGET" in
  *sitemap*) SITEMAP_URL="$TARGET" ;;
  http*)     SITEMAP_URL="${TARGET%/}/sitemap.xml" ;;
  *)         SITEMAP_URL="https://${TARGET#//}/sitemap.xml" ;;
esac

DOMAIN=$(echo "$SITEMAP_URL" | sed -E 's|^https?://||; s|/.*||')
[ -z "$OUT" ] && OUT="tests/private-fixtures/site-$DOMAIN"
mkdir -p "$OUT"

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

# ── Fetch + aggregate sitemap(s) ─────────────────────────────────────────
echo "==> Fetching sitemap: $SITEMAP_URL" >&2
curl -sfL -A "$UA" "$SITEMAP_URL" > "$OUT/sitemap.xml" || {
  echo "FAIL: cannot fetch $SITEMAP_URL" >&2; exit 1
}

if grep -q "<sitemap>" "$OUT/sitemap.xml"; then
  SUB_COUNT=$(grep -c "<sitemap>" "$OUT/sitemap.xml")
  echo "    sitemap index with $SUB_COUNT sub-sitemaps — aggregating all" >&2
  : > "$OUT/sitemap-all.xml"
  grep -oE "<loc>[^<]+</loc>" "$OUT/sitemap.xml" \
    | sed -e 's|<loc>||' -e 's|</loc>||' \
    | while read -r SUB; do
        curl -sfL -A "$UA" "$SUB" >> "$OUT/sitemap-all.xml" 2>/dev/null || true
      done
  mv "$OUT/sitemap-all.xml" "$OUT/sitemap.xml"
fi

grep -oE "<loc>[^<]+</loc>" "$OUT/sitemap.xml" \
  | sed -e 's|<loc>||' -e 's|</loc>||' \
  | head -"$LIMIT" > "$OUT/urls.txt"

URL_COUNT=$(wc -l < "$OUT/urls.txt" | tr -d ' ')
echo "==> Auditing $URL_COUNT pages (limit=$LIMIT, workers=$WORKERS)" >&2

# ── Run page_score on each URL in parallel (background jobs + wait) ─────
mkdir -p "$OUT/pages"

run_one() {
  local URL="$1"
  local SLUG
  SLUG=$(echo "$URL" | sed 's|https\?://||; s|[^a-zA-Z0-9]|_|g' | cut -c1-80)
  local OUTFILE="$OUT/pages/$SLUG.json"
  "$PY" "$SKILL_DIR/scripts/page_score.py" "$URL" --format json $NO_PSI \
    > "$OUTFILE" 2>/dev/null || echo "  FAIL $URL" >&2
  echo "  done $URL" >&2
}

JOB_COUNT=0
while read -r URL; do
  [ -z "$URL" ] && continue
  run_one "$URL" &
  JOB_COUNT=$((JOB_COUNT + 1))
  if [ "$((JOB_COUNT % WORKERS))" -eq 0 ]; then
    wait   # throttle
  fi
done < "$OUT/urls.txt"
wait

# ── Aggregate ────────────────────────────────────────────────────────────
"$PY" <<PY
import json, statistics
from pathlib import Path
from datetime import datetime, timezone

OUT = Path("$OUT/pages")
rows = []
for fn in sorted(OUT.glob("*.json")):
    try:
        d = json.loads(fn.read_text())
        rows.append({
            "url": d["target"],
            "score": d["summary"]["health_score"],
            "by_category": {k: v.get("score") for k, v in d["summary"]["by_category"].items()},
            "findings": d["summary"]["all_findings"],
        })
    except Exception:
        pass

if not rows:
    print("No valid page audits.")
    raise SystemExit(1)

scores = [r["score"] for r in rows]
avg = statistics.mean(scores)
med = statistics.median(scores)
sd = statistics.stdev(scores) if len(scores) > 1 else 0

# Outliers
underperformers = sorted([r for r in rows if r["score"] < avg - sd],
                         key=lambda r: r["score"])

# Aggregate findings across all pages — top recurring issues
finding_freq = {}
for r in rows:
    for f in r["findings"]:
        key = (f["severity"], f["checker"], f["text"])
        finding_freq[key] = finding_freq.get(key, 0) + 1
top_findings = sorted(finding_freq.items(), key=lambda x: -x[1])[:15]

# Category averages
cats = {}
for r in rows:
    for c, s in r["by_category"].items():
        if s is None: continue
        cats.setdefault(c, []).append(s)
cat_avgs = {c: round(statistics.mean(v)) for c, v in cats.items()}

# Markdown report
score_emoji = "🟢" if avg >= 80 else "🟡" if avg >= 60 else "🔴"
md = []
md.append(f"# Site SEO Audit Report")
md.append(f"")
md.append(f"**Domain:** $DOMAIN")
md.append(f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
md.append(f"**Pages audited:** {len(rows)}")
md.append(f"")
md.append(f"## Overall Health Score: {score_emoji} {avg:.0f}/100")
md.append(f"")
md.append(f"| Metric | Value |")
md.append(f"|--------|-------|")
md.append(f"| Mean score | {avg:.1f} |")
md.append(f"| Median score | {med:.0f} |")
md.append(f"| Std deviation | {sd:.1f} |")
md.append(f"| Min / Max | {min(scores)} / {max(scores)} |")
md.append(f"")
md.append(f"## Average by category")
md.append(f"")
md.append(f"| Category | Score |")
md.append(f"|----------|-------|")
for c, v in sorted(cat_avgs.items()):
    md.append(f"| {c} | {v}/100 |")

md.append(f"")
md.append(f"## Top recurring findings (across all pages)")
md.append(f"")
md.append(f"| Count | Severity | Checker | Issue |")
md.append(f"|-------|----------|---------|-------|")
for (sev, ck, text), cnt in top_findings:
    md.append(f"| {cnt} | {sev} | {ck} | {text[:80]} |")

md.append(f"")
md.append(f"## Under-performers (>1σ below mean)")
md.append(f"")
if underperformers:
    md.append(f"| Score | URL |")
    md.append(f"|-------|-----|")
    for r in underperformers[:15]:
        md.append(f"| {r['score']} | {r['url']} |")
else:
    md.append("_No outliers — site is consistent._")

md.append(f"")
md.append(f"## Per-page summary")
md.append(f"")
md.append(f"| Score | URL |")
md.append(f"|-------|-----|")
for r in sorted(rows, key=lambda x: x["score"]):
    md.append(f"| {r['score']} | {r['url'][:90]} |")

md.append(f"")
md.append(f"---")
md.append(f"_Generated by amazing-seo-skill \`tools/site_audit.sh\`. "
          f"Per-page JSON in: \`$OUT/pages/\`._")

Path("$OUT/REPORT.md").write_text("\n".join(md))
print("\n".join(md))
PY

echo "" >&2
echo "==> Report saved: $OUT/REPORT.md" >&2
echo "    Per-page JSON: $OUT/pages/" >&2

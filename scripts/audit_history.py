#!/usr/bin/env python3
"""
Audit history store + trend reporter.

Why it matters:
  - SEO is a long-horizon discipline — what matters is the *trend*, not
    one snapshot. Did the Health Score drop after that redesign? Did the
    AI Visibility Score recover after we added llms.txt?
  - Tracks per-component drift over time: schema completeness creeping
    down (CMS update broke markup?), CWV degradation, broken-link growth.
  - Compares two runs to surface what changed — for client reports,
    A/B testing, or post-deploy verification.

Storage:
  Plain SQLite at `~/.amazing-seo-skill/history.db` (override with
  `AMAZING_SEO_HISTORY_DB` env var). No external service, no auth, single
  file you can copy to back up. Schema:

    runs(id INTEGER PK, ts TEXT, url TEXT, score INTEGER, payload TEXT JSON)
    findings(id INTEGER PK, run_id INTEGER, severity TEXT, checker TEXT, text TEXT)

Commands:
  store  <json_file>         Insert a page_score.py JSON into history.
                              (Use page_score.py --format json | audit_history.py store -)
  list   [url]               Show all runs (optionally filter by URL).
  diff   <run_id_a> <run_id_b>
                              Compare two runs: score delta + findings
                              added/removed.
  trend  <url> [--last N]    Last N runs for a URL with delta vs previous.
  prune  --older-than DAYS   Delete runs older than N days.

Exit code:
  0 = success
  1 = bad input
  2 = `diff`/`trend` found regressions (score dropped, new P0 findings)

Usage:
  page_score.py https://example.com --format json | audit_history.py store -
  audit_history.py list https://example.com
  audit_history.py trend https://example.com --last 10
  audit_history.py diff 12 15
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _db_path() -> Path:
    override = os.environ.get("AMAZING_SEO_HISTORY_DB")
    if override:
        return Path(override)
    p = Path.home() / ".amazing-seo-skill" / "history.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            url TEXT NOT NULL,
            score INTEGER,
            payload TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            severity TEXT,
            checker TEXT,
            text TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_url ON runs(url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts)")
    return conn


def cmd_store(args) -> int:
    if args.input == "-":
        payload_text = sys.stdin.read()
    else:
        payload_text = Path(args.input).read_text()
    try:
        data = json.loads(payload_text)
    except json.JSONDecodeError as e:
        print(f"ERROR: input is not valid JSON: {e}", file=sys.stderr)
        return 1

    url = data.get("target") or data.get("url")
    summary = data.get("summary") or {}
    score = summary.get("health_score") or data.get("ai_visibility_score")
    findings = summary.get("all_findings") or []

    if not url or score is None:
        print("ERROR: JSON does not look like page_score.py or ai_visibility_score.py output",
              file=sys.stderr)
        return 1

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO runs (ts, url, score, payload) VALUES (?, ?, ?, ?)",
            (ts, url, int(score), json.dumps(data, ensure_ascii=False)),
        )
        run_id = cur.lastrowid
        for f in findings:
            conn.execute(
                "INSERT INTO findings (run_id, severity, checker, text) VALUES (?, ?, ?, ?)",
                (run_id, f.get("severity"), f.get("checker"), f.get("text")),
            )
        conn.commit()

    print(json.dumps({"stored": True, "run_id": run_id, "url": url, "score": score, "ts": ts}))
    return 0


def cmd_list(args) -> int:
    with _connect() as conn:
        if args.url:
            rows = conn.execute(
                "SELECT id, ts, url, score FROM runs WHERE url=? ORDER BY ts DESC", (args.url,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, ts, url, score FROM runs ORDER BY ts DESC LIMIT 50",
            ).fetchall()
    out = [{"id": r[0], "ts": r[1], "url": r[2], "score": r[3]} for r in rows]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_diff(args) -> int:
    with _connect() as conn:
        a = conn.execute("SELECT id, ts, url, score, payload FROM runs WHERE id=?",
                         (args.run_a,)).fetchone()
        b = conn.execute("SELECT id, ts, url, score, payload FROM runs WHERE id=?",
                         (args.run_b,)).fetchone()
        if not a or not b:
            print(json.dumps({"error": "one or both run_ids not found"}), file=sys.stderr)
            return 1
        a_findings = conn.execute(
            "SELECT severity, checker, text FROM findings WHERE run_id=?", (args.run_a,)
        ).fetchall()
        b_findings = conn.execute(
            "SELECT severity, checker, text FROM findings WHERE run_id=?", (args.run_b,)
        ).fetchall()

    score_delta = b[3] - a[3]
    set_a = {(s, c, t) for s, c, t in a_findings}
    set_b = {(s, c, t) for s, c, t in b_findings}
    added = sorted(set_b - set_a)
    removed = sorted(set_a - set_b)

    out = {
        "run_a": {"id": a[0], "ts": a[1], "url": a[2], "score": a[3]},
        "run_b": {"id": b[0], "ts": b[1], "url": b[2], "score": b[3]},
        "score_delta": score_delta,
        "findings_added": [{"severity": s, "checker": c, "text": t} for s, c, t in added],
        "findings_removed": [{"severity": s, "checker": c, "text": t} for s, c, t in removed],
        "verdict": (
            "improved" if score_delta > 0 and not any(s == "P0" for s, _, _ in added) else
            "regressed" if score_delta < 0 or any(s == "P0" for s, _, _ in added) else
            "unchanged"
        ),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if out["verdict"] == "regressed" else 0


def cmd_trend(args) -> int:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, ts, score FROM runs WHERE url=? ORDER BY ts DESC LIMIT ?",
            (args.url, args.last),
        ).fetchall()

    if not rows:
        print(json.dumps({"error": f"no runs for {args.url}"}), file=sys.stderr)
        return 1

    rows.reverse()  # oldest first for trend reading
    history = []
    prev = None
    for run_id, ts, score in rows:
        delta = score - prev if prev is not None else None
        history.append({"id": run_id, "ts": ts, "score": score, "delta_vs_prev": delta})
        prev = score

    first = rows[0][2]
    last = rows[-1][2]
    print(json.dumps({
        "url": args.url,
        "runs_count": len(rows),
        "first_score": first,
        "latest_score": last,
        "overall_delta": last - first,
        "history": history,
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_prune(args) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.older_than)).isoformat()
    with _connect() as conn:
        deleted = conn.execute("DELETE FROM runs WHERE ts < ?", (cutoff,)).rowcount
        conn.execute("DELETE FROM findings WHERE run_id NOT IN (SELECT id FROM runs)")
        conn.commit()
    print(json.dumps({"pruned_runs": deleted, "cutoff": cutoff}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_store = sub.add_parser("store", help="store a page_score JSON into history")
    p_store.add_argument("input", help="JSON file path or '-' for stdin")
    p_store.set_defaults(func=cmd_store)

    p_list = sub.add_parser("list", help="list past runs")
    p_list.add_argument("url", nargs="?", help="filter by URL (optional)")
    p_list.set_defaults(func=cmd_list)

    p_diff = sub.add_parser("diff", help="compare two runs")
    p_diff.add_argument("run_a", type=int)
    p_diff.add_argument("run_b", type=int)
    p_diff.set_defaults(func=cmd_diff)

    p_trend = sub.add_parser("trend", help="show trend for a URL")
    p_trend.add_argument("url")
    p_trend.add_argument("--last", type=int, default=10)
    p_trend.set_defaults(func=cmd_trend)

    p_prune = sub.add_parser("prune", help="delete old runs")
    p_prune.add_argument("--older-than", type=int, default=180)
    p_prune.set_defaults(func=cmd_prune)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

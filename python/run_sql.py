"""Run every statement of a .sql file against InfluxDB 3 and print the results (Roadmap P6).

Statements are separated by ';'. The '--' comment lines directly above a statement are
printed as its title. Read-only use is intended (SELECT queries).

Usage:
  python python/run_sql.py queries/weather_analysis/01_summary_by_location.sql
  python python/run_sql.py queries/weather_analysis/03_yagi_hanoi.sql --max-rows 200
"""

import argparse
import dataclasses
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

# Reconfigure stdout/stderr to UTF-8 (Windows console prints Vietnamese text)
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from influxdb_client_3 import InfluxDBClient3

from config import InfluxDBConfig
from weather_schema import DEFAULT_DATABASE


def split_statements(sql_text: str) -> List[Tuple[str, str]]:
    """Split a SQL script into (title, statement) pairs.

    A statement ends at a line whose code part (before any '--' comment) ends with ';',
    so semicolons inside comments are ignored. The title is the block of '--' comment
    lines directly above the statement; a blank or '-- ====' separator line resets it.
    """
    results: List[Tuple[str, str]] = []
    title_lines: List[str] = []
    sql_lines: List[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not sql_lines:
            if not stripped:
                title_lines = []
                continue
            if stripped.startswith("--"):
                text = stripped.lstrip("-").strip()
                title_lines = title_lines + [text] if text.strip("=- ") else []
                continue
        code = line.split("--", 1)[0].rstrip()
        if code.endswith(";"):
            sql_lines.append(code[:-1])
            results.append((" | ".join(title_lines), "\n".join(sql_lines).strip()))
            title_lines, sql_lines = [], []
        else:
            sql_lines.append(line)
    if "\n".join(sql_lines).strip():
        results.append((" | ".join(title_lines), "\n".join(sql_lines).strip()))
    return results


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if abs(value) < 1e6 else f"{value:.4g}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def print_table(rows: List[dict], max_rows: int) -> None:
    if not rows:
        print("  (no rows)")
        return
    columns = list(rows[0].keys())
    shown = rows[:max_rows]
    cells = [[format_value(r[c]) for c in columns] for r in shown]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(columns)]
    print("  " + " | ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  " + "-+-".join("-" * w for w in widths))
    for row in cells:
        print("  " + " | ".join(v.rjust(w) for v, w in zip(row, widths)))
    if len(rows) > max_rows:
        print(f"  ... {len(rows) - max_rows} more row(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a .sql file against InfluxDB 3 (statement by statement).")
    parser.add_argument("sql_file", type=Path)
    parser.add_argument("--database", default=os.getenv("WEATHER_INFLUXDB_DATABASE", DEFAULT_DATABASE),
                        help=f"Database (default: $WEATHER_INFLUXDB_DATABASE or '{DEFAULT_DATABASE}')")
    parser.add_argument("--max-rows", type=int, default=40, help="Rows to print per statement (default: 40)")
    args = parser.parse_args()

    try:
        statements = split_statements(args.sql_file.read_text(encoding="utf-8"))
        cfg = dataclasses.replace(InfluxDBConfig.load(), database=args.database)
        client = InfluxDBClient3(host=cfg.url, token=cfg.token, database=cfg.database, verify_ssl=False)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] {args.sql_file} — {len(statements)} statement(s) on database '{args.database}'")
    failed = 0
    for i, (title, statement) in enumerate(statements, start=1):
        print(f"\n[{i}] {title or '(untitled)'}")
        started = time.perf_counter()
        try:
            rows = client.query(query=statement).to_pylist()
        except Exception as exc:
            failed += 1
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        print_table(rows, args.max_rows)
        print(f"  ({len(rows)} row(s), {time.perf_counter() - started:.2f}s)")

    if failed:
        print(f"\n[ERROR] {failed} statement(s) failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

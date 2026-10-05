"""Weather Collector CLI for InfluxDB 3 Core (Roadmap P3 + P4).

Fetches hourly weather data from Open-Meteo, cleans it (weather_cleaning.py) and
writes it in batches to InfluxDB 3, then reads it back to verify the ingestion.

Sub-commands:
  backfill  Archive API (historical, best_match) for a date range, in chunks.
            Archive data always wins: it overwrites forecast data for the same hour.
  recent    Forecast API for the last N days. Hours already covered by archive data
            are skipped so provisional forecast values never overwrite archive values.
            --interval-minutes > 0 repeats the collection (near real-time mode).
  verify    Read-only summary of the weather table: rows, time range, gaps, nulls.

Examples:
  python python/weather_collector.py backfill --start 2024-01-01
  python python/weather_collector.py recent --past-days 7
  python python/weather_collector.py verify
"""

import argparse
import dataclasses
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

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
from open_meteo import LOCATIONS, fetch_archive, fetch_forecast, parse_location_keys
from weather_cleaning import CleaningReport, Record, clean_payload, drop_covered_by_archive
from weather_schema import (
    DATA_SOURCE_FIELD,
    DEFAULT_DATABASE,
    LOCATION_TAG,
    MEASUREMENT_FIELDS,
    TABLE,
    to_point,
)

REQUEST_PAUSE_SECONDS = 0.5  # be polite to the free API between requests


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def date_chunks(start: date, end: date, chunk_days: int) -> List[Tuple[date, date]]:
    """Split [start, end] (inclusive) into consecutive inclusive chunks of at most chunk_days."""
    if chunk_days < 1:
        raise ValueError("chunk_days must be >= 1")
    if end < start:
        raise ValueError(f"end date {end} is before start date {start}")
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def sql_timestamp(value: datetime) -> str:
    """Format an aware datetime as a DataFusion UTC timestamp literal."""
    return f"TIMESTAMP '{value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}'"


def as_utc(value: Any) -> Any:
    """Query results come back as naive datetimes in UTC; make them timezone-aware."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------------------
# InfluxDB I/O
# ---------------------------------------------------------------------------

def connect(database: str) -> InfluxDBClient3:
    cfg = dataclasses.replace(InfluxDBConfig.load(), database=database)
    print(f"[INFO] InfluxDB: {cfg.sanitized_summary()} | table: {TABLE}")
    return InfluxDBClient3(host=cfg.url, token=cfg.token, database=cfg.database, verify_ssl=False)


def query_rows(client: InfluxDBClient3, sql: str) -> List[Dict[str, Any]]:
    rows = client.query(query=sql).to_pylist()
    return [{k: as_utc(v) for k, v in row.items()} for row in rows]


def table_exists(client: InfluxDBClient3) -> bool:
    rows = query_rows(
        client,
        f"SELECT table_name FROM information_schema.tables WHERE table_name = '{TABLE}'",
    )
    return bool(rows)


def archive_cutoffs(client: InfluxDBClient3) -> Dict[str, datetime]:
    """Latest archive hour per location (forecast data must stay after it)."""
    if not table_exists(client):
        return {}
    rows = query_rows(
        client,
        f"SELECT {LOCATION_TAG}, max(time) AS last_time FROM {TABLE} "
        f"WHERE {DATA_SOURCE_FIELD} = 'archive' GROUP BY {LOCATION_TAG}",
    )
    return {r[LOCATION_TAG]: r["last_time"] for r in rows}


def write_records(client: InfluxDBClient3, records: List[Record], batch_size: int) -> int:
    """Write cleaned records in batches (synchronous writes). Returns number of points written."""
    written = 0
    for i in range(0, len(records), batch_size):
        batch = [to_point(r) for r in records[i:i + batch_size]]
        client.write(record=batch)
        written += len(batch)
    return written


def verify(
    client: InfluxDBClient3,
    locations: List[str],
    window: Optional[Tuple[datetime, datetime]] = None,
    expected_rows: Optional[Dict[str, int]] = None,
) -> bool:
    """Read the data back and print per-location rows, time range, hourly gaps and nulls.

    window: inclusive (first_hour, last_hour) to restrict the check; None = whole table.
    expected_rows: rows each location must have inside the window; mismatch -> False.
    """
    if not table_exists(client):
        print(f"[ERROR] Table '{TABLE}' does not exist in this database.", file=sys.stderr)
        return False

    where = f"WHERE {LOCATION_TAG} IN ({', '.join(repr(k) for k in locations)})"
    if window:
        where += f" AND time >= {sql_timestamp(window[0])} AND time <= {sql_timestamp(window[1])}"
    field_counts = ", ".join(f"count({f}) AS {f}" for f in MEASUREMENT_FIELDS)
    summary = query_rows(
        client,
        f"SELECT {LOCATION_TAG}, count(*) AS total_rows, min(time) AS first_time, "
        f"max(time) AS last_time, {field_counts} FROM {TABLE} {where} "
        f"GROUP BY {LOCATION_TAG} ORDER BY {LOCATION_TAG}",
    )
    sources = query_rows(
        client,
        f"SELECT {LOCATION_TAG}, {DATA_SOURCE_FIELD}, count(*) AS n FROM {TABLE} {where} "
        f"GROUP BY {LOCATION_TAG}, {DATA_SOURCE_FIELD} ORDER BY {LOCATION_TAG}, {DATA_SOURCE_FIELD}",
    )

    scope = f"{window[0].isoformat()} .. {window[1].isoformat()}" if window else "whole table"
    print(f"\n[INFO] Verification of '{TABLE}' ({scope})")
    ok = True
    found = {row[LOCATION_TAG]: row for row in summary}
    for key in locations:
        row = found.get(key)
        if row is None:
            print(f"  {key:7s} rows=0")
            ok = ok and not (expected_rows and expected_rows.get(key))
            continue
        total = row["total_rows"]
        span_hours = int((row["last_time"] - row["first_time"]).total_seconds() // 3600) + 1
        by_source = {s[DATA_SOURCE_FIELD]: s["n"] for s in sources if s[LOCATION_TAG] == key}
        nulls = {f: total - row[f] for f in MEASUREMENT_FIELDS if total - row[f]}
        print(f"  {key:7s} rows={total:<7d} {row['first_time'].isoformat()} .. {row['last_time'].isoformat()}"
              f" | missing hours in span={span_hours - total} | by source={by_source}"
              f" | nulls={nulls or 'none'}")
        if expected_rows is not None and total != expected_rows.get(key, 0):
            print(f"[ERROR] {key}: expected {expected_rows.get(key, 0)} rows in window, found {total}",
                  file=sys.stderr)
            ok = False
    return ok


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def run_backfill(args: argparse.Namespace) -> bool:
    locations = parse_location_keys(args.locations)
    chunks = date_chunks(args.start, args.end, args.chunk_days)
    client = connect(args.database)
    now = datetime.now(timezone.utc)

    total_report = CleaningReport()
    expected: Dict[str, int] = {}
    print(f"[INFO] Backfill {args.start} .. {args.end} | locations={locations} | "
          f"{len(chunks)} chunk(s) of <= {args.chunk_days} days")

    for key in locations:
        expected[key] = 0
        for chunk_start, chunk_end in chunks:
            payload = fetch_archive(key, chunk_start, chunk_end)
            records, report = clean_payload(payload, key, "archive", now)
            written = write_records(client, records, args.batch_size)
            expected[key] += written
            total_report.merge(report)
            print(f"[INFO] {key:7s} {chunk_start} .. {chunk_end}: fetched {report.rows_in}, "
                  f"wrote {written} points")
            time.sleep(REQUEST_PAUSE_SECONDS)

    print("\n[INFO] Cleaning report (backfill):")
    for line in total_report.format_lines():
        print(f"  {line}")

    window = (
        datetime.combine(args.start, datetime.min.time(), tzinfo=timezone.utc),
        datetime.combine(args.end, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=23),
    )
    return verify(client, locations, window, expected)


def collect_recent_once(client: InfluxDBClient3, locations: List[str], past_days: int,
                        batch_size: int) -> Tuple[bool, CleaningReport]:
    now = datetime.now(timezone.utc)
    cutoffs = archive_cutoffs(client)
    total_report = CleaningReport()
    # Per-location window of the hours written now (cutoffs may differ between locations)
    windows: Dict[str, Tuple[datetime, datetime, int]] = {}

    for key in locations:
        payload = fetch_forecast(key, past_days)
        records, report = clean_payload(payload, key, "forecast", now)
        records = drop_covered_by_archive(records, cutoffs.get(key), report)
        written = write_records(client, records, batch_size)
        total_report.merge(report)
        if records:
            windows[key] = (records[0]["time"], records[-1]["time"], written)
        cutoff_text = cutoffs[key].isoformat() if key in cutoffs else "none"
        print(f"[INFO] {key:7s} forecast: fetched {report.rows_in}, wrote {written} points "
              f"(archive cutoff: {cutoff_text})")
        time.sleep(REQUEST_PAUSE_SECONDS)

    print("\n[INFO] Cleaning report (recent):")
    for line in total_report.format_lines():
        print(f"  {line}")

    if not windows:
        print("[INFO] Nothing new to write (all hours already covered by archive data).")
        return True, total_report
    ok = all([  # list, not generator: report every location even if one fails
        verify(client, [key], (first, last), {key: written})
        for key, (first, last, written) in windows.items()
    ])
    return ok, total_report


def run_recent(args: argparse.Namespace) -> bool:
    locations = parse_location_keys(args.locations)
    client = connect(args.database)
    if args.interval_minutes <= 0:
        ok, _ = collect_recent_once(client, locations, args.past_days, args.batch_size)
        return ok

    print(f"[INFO] Near real-time mode: collecting every {args.interval_minutes} min (Ctrl+C to stop)")
    try:
        while True:
            print(f"\n[INFO] Run at {datetime.now(timezone.utc).isoformat()}")
            ok, _ = collect_recent_once(client, locations, args.past_days, args.batch_size)
            if not ok:
                return False
            time.sleep(args.interval_minutes * 60)
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user (SIGINT).")
    return True


def run_verify(args: argparse.Namespace) -> bool:
    client = connect(args.database)
    return verify(client, parse_location_keys(args.locations))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date '{value}' (expected YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--database",
        default=os.getenv("WEATHER_INFLUXDB_DATABASE", DEFAULT_DATABASE),
        help=f"Target database (default: $WEATHER_INFLUXDB_DATABASE or '{DEFAULT_DATABASE}')",
    )
    common.add_argument(
        "--locations",
        default="all",
        help=f"Comma-separated location keys or 'all' (default). Valid: {','.join(LOCATIONS)}",
    )

    parser = argparse.ArgumentParser(description="Open-Meteo -> cleaning -> InfluxDB 3 weather collector.")
    sub = parser.add_subparsers(dest="command", required=True)

    yesterday_utc = datetime.now(timezone.utc).date() - timedelta(days=1)
    backfill = sub.add_parser("backfill", parents=[common], help="Historical data from the Archive API")
    backfill.add_argument("--start", type=parse_date, default=date(2024, 1, 1),
                          help="First day, UTC (default: 2024-01-01)")
    backfill.add_argument("--end", type=parse_date, default=yesterday_utc,
                          help=f"Last day inclusive, UTC (default: yesterday = {yesterday_utc})")
    backfill.add_argument("--chunk-days", type=int, default=365,
                          help="Days per Archive API request (default: 365)")
    backfill.add_argument("--batch-size", type=int, default=5000,
                          help="Points per InfluxDB write (default: 5000)")

    recent = sub.add_parser("recent", parents=[common], help="Recent hours from the Forecast API")
    recent.add_argument("--past-days", type=int, default=7, choices=range(0, 93), metavar="0-92",
                        help="Days of past hours to fetch (default: 7)")
    recent.add_argument("--interval-minutes", type=float, default=0,
                        help="Repeat every N minutes; 0 = run once (default: 0)")
    recent.add_argument("--batch-size", type=int, default=5000,
                        help="Points per InfluxDB write (default: 5000)")

    sub.add_parser("verify", parents=[common], help="Read-only summary of the stored data")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    handlers = {"backfill": run_backfill, "recent": run_recent, "verify": run_verify}
    try:
        ok = handlers[args.command](args)
    except (RuntimeError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # InfluxDB client errors (connection, write rejected, query failure)
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not ok:
        print("[ERROR] Verification failed.", file=sys.stderr)
        sys.exit(1)
    print("\n[INFO] Done.")


if __name__ == "__main__":
    main()

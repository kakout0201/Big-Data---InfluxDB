"""Run the selected anomaly detectors on all locations and rebuild weather_anomalies (Roadmap P7).

Method selection agreed with the user on 2026-10-06 (see CLAUDE.md "Anomaly Detection"):
  pressure_msl_hpa  climate_zscore k=3, low                   (storms)
  wind_gusts_ms     iqr k=3 per local month + threshold 17.2 m/s (gió giật cấp 8)
  rain_24h_mm       iqr k=3 on wet periods (>= 1 mm) per month + threshold 50 mm (mưa to)
  temperature_c     persistent_climate_zscore 168 h mean z >= 1.0, high (heatwaves)
  temperature_c, pressure_msl_hpa  stuck values >= 6 h        (data quality)

weather_anomalies is derived data: every run deletes the table and writes it again from
scratch, so no stale flags survive a parameter change. Afterwards the rows are counted per
(location, field, method, direction) and compared with what was written.

Usage:
  python python/anomaly_job.py --dry-run     # compute and print counts only
  python python/anomaly_job.py               # delete + rewrite + verify
"""

import argparse
import dataclasses
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Tuple

# Reconfigure stdout/stderr to UTF-8 (Windows console prints Vietnamese text)
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from influxdb_client_3 import InfluxDBClient3

from config import InfluxDBConfig
from evaluate_anomaly import load_series
from open_meteo import LOCATIONS, parse_location_keys
from run_sql import print_table
from weather_anomaly import (
    HIGH, LOW, Detection, climate_zscore, gust_severity, heat_severity, iqr_detect,
    local_calendar, persistent_climate_zscore, rain_24h_severity, rolling_max, stuck_detect,
    threshold_detect, zscore_severity,
)
from weather_schema import ANOMALY_TABLE, DEFAULT_DATABASE, anomaly_to_point

Series = Dict[str, np.ndarray]
UNITS = {"temperature_c": "°C", "pressure_msl_hpa": " hPa", "wind_gusts_ms": " m/s", "rain_24h_mm": " mm"}
STUCK_LABEL = "nghi lỗi dữ liệu (giá trị kẹt)"


@dataclass(frozen=True)
class SelectedMethod:
    field: str
    direction: str                                        # tag value: high | low | none
    k: float                                              # method parameter stored with each row
    detect: Callable[[np.ndarray, Series], Detection]
    severity: Callable[[Detection, int, Series], str]


def selected_methods() -> List[SelectedMethod]:
    """The agreed production configuration (same parameters as evaluate_anomaly.py)."""
    def months(t: np.ndarray) -> np.ndarray:
        return local_calendar(t)[1]

    return [
        SelectedMethod("pressure_msl_hpa", LOW, 3.0,
                       lambda t, d: climate_zscore(t, d["pressure_msl_hpa"], 3.0, LOW),
                       lambda det, i, d: "áp suất thấp bất thường, " + zscore_severity(det.scores[i])),
        SelectedMethod("wind_gusts_ms", HIGH, 3.0,
                       lambda t, d: iqr_detect(d["wind_gusts_ms"], 3.0, HIGH, groups=months(t)),
                       lambda det, i, d: gust_severity(d["wind_gusts_ms"][i])),
        SelectedMethod("wind_gusts_ms", HIGH, 17.2,
                       lambda t, d: threshold_detect(d["wind_gusts_ms"], 17.2, HIGH, "gió giật cấp 8"),
                       lambda det, i, d: gust_severity(d["wind_gusts_ms"][i])),
        SelectedMethod("rain_24h_mm", HIGH, 3.0,
                       lambda t, d: iqr_detect(d["rain_24h_mm"], 3.0, HIGH,
                                               reference_mask=np.nan_to_num(d["rain_24h_mm"]) >= 1.0,
                                               groups=months(t)),
                       lambda det, i, d: rain_24h_severity(d["rain_24h_mm"][i])),
        SelectedMethod("rain_24h_mm", HIGH, 50.0,
                       lambda t, d: threshold_detect(d["rain_24h_mm"], 50.0, HIGH, "mưa to 24h"),
                       lambda det, i, d: rain_24h_severity(d["rain_24h_mm"][i])),
        SelectedMethod("temperature_c", HIGH, 1.0,
                       lambda t, d: persistent_climate_zscore(t, d["temperature_c"], 168, 1.0, HIGH),
                       lambda det, i, d: f"{heat_severity(d['tmax_24h'][i])} "
                                         f"(Tmax 24h {d['tmax_24h'][i]:.1f}°C)"),
        SelectedMethod("temperature_c", "none", 6,
                       lambda t, d: stuck_detect(d["temperature_c"], 6),
                       lambda det, i, d: STUCK_LABEL),
        SelectedMethod("pressure_msl_hpa", "none", 6,
                       lambda t, d: stuck_detect(d["pressure_msl_hpa"], 6),
                       lambda det, i, d: STUCK_LABEL),
    ]


def build_records(location: str, times: np.ndarray, data: Series, detected_at: str) -> List[Dict]:
    """Run every selected method on one location and turn each flag into a row dict."""
    data = {**data, "tmax_24h": rolling_max(data["temperature_c"], 24)}
    records = []
    for spec in selected_methods():
        det = spec.detect(times, data)
        raw = data[spec.field]
        for i in np.flatnonzero(det.flags):
            records.append({
                "time": times[i].astype("datetime64[s]").astype(datetime).replace(tzinfo=timezone.utc),
                "location": location,
                "field": spec.field,
                "method": det.method,
                "direction": spec.direction,
                "value": det.value_at(i, raw[i]),
                "baseline": float(det.baseline[i]),
                "score": float(det.scores[i]),
                "k": float(spec.k),
                "severity": spec.severity(det, i, data),
                "reason": det.reason(i, raw[i], UNITS[spec.field]),
                "detected_at": detected_at,
            })
    return records


def table_exists(client: InfluxDBClient3) -> bool:
    rows = client.query(
        f"SELECT table_name FROM information_schema.tables WHERE table_name = '{ANOMALY_TABLE}'"
    ).to_pylist()
    return bool(rows)


def delete_table(client: InfluxDBClient3, database: str) -> None:
    """Hard-delete weather_anomalies via the influxdb3 CLI inside the container."""
    if not table_exists(client):
        print(f"[INFO] Table '{ANOMALY_TABLE}' does not exist yet; nothing to delete.")
        return
    result = subprocess.run(
        ["docker", "exec", "influxdb3-core", "influxdb3", "delete", "table", ANOMALY_TABLE,
         "-d", database, "--hard-delete", "now", "-y"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"delete table failed: {result.stderr.strip() or result.stdout.strip()}")
    for _ in range(30):                     # wait until the catalog no longer lists the table
        if not table_exists(client):
            print(f"[INFO] Deleted table '{ANOMALY_TABLE}'.")
            return
        time.sleep(1)
    raise RuntimeError(f"table '{ANOMALY_TABLE}' still listed 30 s after deletion")


def write_records(client: InfluxDBClient3, records: List[Dict], batch_size: int) -> None:
    for i in range(0, len(records), batch_size):
        client.write(record=[anomaly_to_point(r) for r in records[i:i + batch_size]])


def counts_by_key(records: List[Dict]) -> Counter:
    return Counter((r["location"], r["field"], r["method"], r["direction"]) for r in records)


def verify(client: InfluxDBClient3, expected: Counter) -> bool:
    rows = client.query(
        f"SELECT location, field, method, direction, count(*) AS n FROM {ANOMALY_TABLE} "
        f"GROUP BY location, field, method, direction ORDER BY location, field, method"
    ).to_pylist()
    found = {(r["location"], r["field"], r["method"], r["direction"]): r["n"] for r in rows}
    table = []
    ok = True
    for key in sorted(set(found) | set(expected)):
        match = found.get(key, 0) == expected.get(key, 0)
        ok &= match
        table.append({"location": key[0], "field": key[1], "method": key[2], "direction": key[3],
                      "written": expected.get(key, 0), "count(*)": found.get(key, 0),
                      "match": "ok" if match else "MISMATCH"})
    print(f"\n[INFO] Verification: count(*) per (location, field, method, direction) in '{ANOMALY_TABLE}'")
    print_table(table, 100)
    print(f"  total written={sum(expected.values())}  total in table={sum(found.values())}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect anomalies and rebuild the weather_anomalies table.")
    parser.add_argument("--database", default=os.getenv("WEATHER_INFLUXDB_DATABASE", DEFAULT_DATABASE))
    parser.add_argument("--locations", default="all", help=f"'all' or comma list of {','.join(LOCATIONS)}")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--dry-run", action="store_true", help="Compute and print counts; do not touch the DB table")
    args = parser.parse_args()

    try:
        locations = parse_location_keys(args.locations)
        if locations != list(LOCATIONS) and not args.dry_run:
            raise ValueError("The table is rebuilt from scratch, so a real run must use --locations all")
        cfg = dataclasses.replace(InfluxDBConfig.load(), database=args.database)
        client = InfluxDBClient3(host=cfg.url, token=cfg.token, database=cfg.database, verify_ssl=False)
        detected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        records: List[Dict] = []
        for location in locations:
            times, data = load_series(client, location)
            loc_records = build_records(location, times, data, detected_at)
            records.extend(loc_records)
            print(f"[INFO] {location:7s} {len(times)} hours analysed "
                  f"({times[0]} .. {times[-1]} UTC) -> {len(loc_records)} anomaly rows")
        expected = counts_by_key(records)

        if args.dry_run:
            print("\n[INFO] Dry run: nothing deleted or written.")
            print_table([{"location": k[0], "field": k[1], "method": k[2], "direction": k[3], "rows": n}
                         for k, n in sorted(expected.items())], 100)
            return

        delete_table(client, args.database)
        write_records(client, records, args.batch_size)
        print(f"[INFO] Wrote {len(records)} rows to '{ANOMALY_TABLE}' (detected_at={detected_at}).")
        ok = verify(client, expected)
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not ok:
        print("[ERROR] Verification failed.", file=sys.stderr)
        sys.exit(1)
    print("\n[INFO] Done.")


if __name__ == "__main__":
    main()

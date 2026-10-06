"""Compare anomaly detection methods on real events and synthetic injections (Roadmap P7).

Reads hourly series from InfluxDB (read-only), runs every method of weather_anomaly.py with
the same parameters, and prints comparison tables:
  Case 1  Typhoon Yagi, Hanoi            2024-09-06 00:00 .. 2024-09-09 00:00 (local, UTC+7)
  Case 2  Heatwave, Ho Chi Minh City     2024-04-01 00:00 .. 2024-05-01 00:00 (local)
  Case 3  Latest hours, Ho Chi Minh City last 72 h up to the newest stored hour
  Case 4  Synthetic spikes + stuck runs injected into HCM 2025 -> precision / recall
Nothing is written to the database.

Usage:
  python python/evaluate_anomaly.py [--k 3.0] [--sensitivity]
"""

import argparse
import dataclasses
import os
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

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
from run_sql import print_table
from weather_anomaly import (
    BOTH, HIGH, LOW, Detection, climate_zscore, confusion, count_episodes, event_metrics,
    global_zscore, inject_anomalies, iqr_detect, local_calendar, persistent_climate_zscore,
    pressure_tendency,
    rolling_sum, rolling_zscore, stuck_detect, threshold_detect,
)
from weather_schema import DEFAULT_DATABASE, TABLE

YEAR = np.timedelta64(8766, "h")   # 365.25 days


@dataclass(frozen=True)
class FieldSpec:
    unit: str
    threshold: Optional[Tuple[float, str]] = None   # (limit, label) of a meteorological criterion
    iqr_reference_min: Optional[float] = None        # IQR quartiles only from values >= this
    tendency: bool = False                           # pressure tendency (3 h fall)
    stuck: bool = False                              # stuck-value detector is meaningful
    persistent: bool = False                         # sustained anomaly (168 h mean climate z)


# Meteorological limits (to be cross-checked with the official NCHMF criteria in the report):
# nắng nóng Tmax >= 35 °C; gió giật cấp 8 Beaufort >= 17.2 m/s; mưa to >= 50 mm / 24 h.
FIELDS: Dict[str, FieldSpec] = {
    "temperature_c": FieldSpec("°C", threshold=(35.0, "nắng nóng"), stuck=True, persistent=True),
    "pressure_msl_hpa": FieldSpec(" hPa", tendency=True, stuck=True),
    "wind_gusts_ms": FieldSpec(" m/s", threshold=(17.2, "gió giật cấp 8")),
    "rain_24h_mm": FieldSpec(" mm", threshold=(50.0, "mưa to 24h"), iqr_reference_min=1.0),
}


def run_methods(times: np.ndarray, values: np.ndarray, field: str, direction: str,
                k: float) -> List[Detection]:
    """Every applicable method with the same k. IQR fences are computed per local month."""
    spec = FIELDS[field]
    _, months, _ = local_calendar(times)
    detections: List[Detection] = []
    if spec.threshold and direction in (HIGH, LOW):
        detections.append(threshold_detect(values, spec.threshold[0], direction, spec.threshold[1]))
    detections.append(global_zscore(values, k, direction))
    detections.append(climate_zscore(times, values, k, direction))
    if spec.persistent and direction in (HIGH, LOW):
        detections.append(persistent_climate_zscore(times, values, 168, 1.0, direction))
    reference = None if spec.iqr_reference_min is None else values >= spec.iqr_reference_min
    iqr_dirs = [direction] if direction in (HIGH, LOW) else [HIGH, LOW]
    iqr_dets = [iqr_detect(values, k, d, reference_mask=reference, groups=months) for d in iqr_dirs]
    if len(iqr_dets) == 2:   # BOTH: merge the two one-sided IQR detectors
        a, b = iqr_dets
        iqr_dets = [dataclasses.replace(a, flags=a.flags | b.flags,
                                        scores=np.where(b.flags, b.scores, a.scores))]
    detections.extend(iqr_dets)
    detections.append(rolling_zscore(values, 24, k, direction))
    detections.append(rolling_zscore(values, 168, k, direction))
    if spec.tendency:
        detections.append(pressure_tendency(values, 3, -3.0))
    if spec.stuck:
        detections.append(stuck_detect(values, 6))
    return detections


# ---------------------------------------------------------------------------
# Data access (read-only)
# ---------------------------------------------------------------------------

def load_series(client: InfluxDBClient3, location: str) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    table = client.query(
        f"SELECT time, temperature_c, pressure_msl_hpa, wind_gusts_ms, precipitation_mm "
        f"FROM {TABLE} WHERE location = '{location}' ORDER BY time"
    )
    times = table.column("time").to_numpy().astype("datetime64[s]")
    steps = np.diff(times)
    if len(steps) and not (steps == np.timedelta64(3600, "s")).all():
        raise RuntimeError(f"{location}: series is not contiguous hourly data; rolling windows assume it is")
    data = {name: table.column(name).to_numpy(zero_copy_only=False).astype(float)
            for name in ("temperature_c", "pressure_msl_hpa", "wind_gusts_ms", "precipitation_mm")}
    data["rain_24h_mm"] = rolling_sum(data["precipitation_mm"], 24)
    return times, data


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def outside_windows(times: np.ndarray, windows: List[Tuple[str, str]]) -> np.ndarray:
    mask = np.ones(len(times), dtype=bool)
    for start, end in windows:
        mask &= ~((times >= np.datetime64(start, "s")) & (times < np.datetime64(end, "s")))
    return mask


def event_table(times, values, field, direction, k, window, peak, labelled_windows) -> List[Dict]:
    span_years = (times[-1] - times[0]) / YEAR
    outside = outside_windows(times, labelled_windows)
    rows = []
    for det in run_methods(times, values, field, direction, k):
        m = event_metrics(times, det.flags, window[0], window[1], peak)
        rows.append({
            "method": det.method,
            "detected": "yes" if m["detected"] else "NO",
            "flagged_h": f"{m['flagged_hours']}/{m['window_hours']}",
            "flagged_days": m["flagged_days"],
            "first_flag_local": (m["first_flag"] + np.timedelta64(7, "h")).astype("datetime64[m]")
            if m["first_flag"] is not None else "",
            "lead_h": "" if m["lead_hours"] is None else m["lead_hours"],
            "alarm_episodes_per_yr_outside": round(count_episodes(det.flags & outside) / span_years, 1),
            "flagged_h_per_yr_outside": round(int((det.flags & outside).sum()) / span_years, 0),
        })
    return rows


def strongest_reasons(times, values, field, direction, k, window, methods: List[str], unit: str) -> None:
    start, end = np.datetime64(window[0], "s"), np.datetime64(window[1], "s")
    in_window = (times >= start) & (times < end)
    for det in run_methods(times, values, field, direction, k):
        if det.method not in methods:
            continue
        hits = np.flatnonzero(det.flags & in_window)
        if not len(hits):
            print(f"  {det.method:15s} — không gắn cờ")
            continue
        strength = np.abs(np.nan_to_num(det.scores[hits]))
        i = hits[int(np.argmax(strength))]
        local = (times[i] + np.timedelta64(7, "h")).astype("datetime64[m]")
        print(f"  {det.method:15s} {local}  {det.reason(i, values[i], unit)}")


def synthetic_table(times, values, field, spike_range, k, seed=42) -> List[Dict]:
    years, _, _ = local_calendar(times)
    segment = np.flatnonzero(years == 2025)
    injected = values.copy()
    seg_values, labels, kind = inject_anomalies(
        values[segment], seed=seed, n_spikes=20, spike_range=spike_range,
        n_stuck=10, stuck_length=8, min_gap=250, spike_sign=BOTH)
    injected[segment] = seg_values
    clean_dets = {d.method: d for d in run_methods(times, values, field, BOTH, k)}
    rows = []
    for det in run_methods(times, injected, field, BOTH, k):
        flags = det.flags[segment]
        c = confusion(flags, labels)
        background = int(clean_dets[det.method].flags[segment].sum())
        rows.append({
            "method": det.method,
            "recall_spike": round(float(flags[kind == 1].mean()), 2),
            "recall_stuck": round(float(flags[kind == 2].mean()), 2),
            "precision": round(c["precision"], 3),
            "f1": round(c["f1"], 3),
            "tp": c["tp"], "fp": c["fp"], "fn": c["fn"],
            "flags_on_clean_2025": background,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare anomaly detection methods (read-only).")
    parser.add_argument("--k", type=float, default=3.0, help="Sensitivity k for z-score / IQR methods (default 3)")
    parser.add_argument("--sensitivity", action="store_true", help="Also print k = 2 / 2.5 / 3 sensitivity tables")
    parser.add_argument("--database", default=os.getenv("WEATHER_INFLUXDB_DATABASE", DEFAULT_DATABASE))
    args = parser.parse_args()

    cfg = dataclasses.replace(InfluxDBConfig.load(), database=args.database)
    client = InfluxDBClient3(host=cfg.url, token=cfg.token, database=cfg.database, verify_ssl=False)
    series = {loc: load_series(client, loc) for loc in ("hanoi", "hcm")}
    k = args.k
    yagi = ("2024-09-05T17:00", "2024-09-08T17:00")
    yagi_peak = "2024-09-07T13:00"          # lowest pressure, 20:00 local
    heat = ("2024-03-31T17:00", "2024-04-30T17:00")
    labelled = {"hanoi": [yagi], "hcm": [heat]}
    print(f"[INFO] k = {k}; data up to {series['hcm'][0][-1]} UTC. Nothing is written to InfluxDB.")

    t, d = series["hanoi"]
    for field, direction in (("pressure_msl_hpa", LOW), ("wind_gusts_ms", HIGH), ("rain_24h_mm", HIGH)):
        print(f"\n=== Ca 1: Bão Yagi, Hà Nội — {field} ({direction}); lead_h = giờ trước áp suất thấp nhất (20:00 07/09)")
        print_table(event_table(t, d[field], field, direction, k, yagi, yagi_peak, labelled["hanoi"]), 20)
    print("\n  Điểm mạnh nhất trong cửa sổ Yagi (pressure_msl_hpa) — lý do gắn cờ:")
    strongest_reasons(t, d["pressure_msl_hpa"], "pressure_msl_hpa", LOW, k, yagi,
                      ["climate_zscore", "rolling_24h", "rolling_168h", "tendency_3h", "global_zscore"], " hPa")

    t, d = series["hcm"]
    print(f"\n=== Ca 2: Nắng nóng TP.HCM 04/2024 — temperature_c (high); flagged_days trên 30 ngày")
    print_table(event_table(t, d["temperature_c"], "temperature_c", HIGH, k, heat, None, labelled["hcm"]), 20)
    print("\n  Điểm mạnh nhất trong tháng 04/2024 — lý do gắn cờ:")
    strongest_reasons(t, d["temperature_c"], "temperature_c", HIGH, k, heat,
                      ["threshold", "climate_zscore", "persistent_climate_zscore", "rolling_168h", "global_zscore"], "°C")

    last = t[-1] + np.timedelta64(1, "h")
    recent = (str(last - np.timedelta64(72, "h")), str(last))
    for field in ("rain_24h_mm", "wind_gusts_ms", "temperature_c"):
        print(f"\n=== Ca 3: TP.HCM 72 giờ gần nhất ({recent[0]} .. {recent[1]} UTC) — {field} (high)")
        print_table(event_table(t, d[field], field, HIGH, k, recent, None, labelled["hcm"]), 20)
    sl = slice(len(t) - 72, len(t))
    print("\n  Lượng mưa 24h và gió giật lớn nhất trong 72 giờ gần nhất:")
    for field, unit in (("rain_24h_mm", " mm"), ("wind_gusts_ms", " m/s"), ("precipitation_mm", " mm/h")):
        i = sl.start + int(np.nanargmax(d[field][sl]))
        print(f"  {field:16s} max {d[field][i]:.1f}{unit} lúc {(t[i] + np.timedelta64(7, 'h')).astype('datetime64[m]')} (giờ VN)")
    strongest_reasons(t, d["rain_24h_mm"], "rain_24h_mm", HIGH, k, recent,
                      ["threshold", "climate_zscore", "iqr", "rolling_24h", "rolling_168h"], " mm")

    for field, spike_range in (("temperature_c", (4.0, 8.0)), ("pressure_msl_hpa", (4.0, 8.0))):
        print(f"\n=== Ca 4: Bất thường giả trong TP.HCM 2025 — {field}: 20 spike ±{spike_range} + 10 stuck × 8h")
        print_table(synthetic_table(t, d[field], field, spike_range, k), 20)

    if args.sensitivity:
        for kk in (2.0, 2.5, 3.0):
            th, dh = series["hanoi"]
            rows = [r for r in event_table(th, dh["pressure_msl_hpa"], "pressure_msl_hpa", LOW, kk,
                                           yagi, yagi_peak, labelled["hanoi"])
                    if r["method"] in ("climate_zscore", "rolling_24h", "rolling_168h", "iqr")]
            print(f"\n=== Độ nhạy k = {kk}: Yagi pressure")
            print_table(rows, 10)
            rows = [r for r in event_table(t, d["temperature_c"], "temperature_c", HIGH, kk,
                                           heat, None, labelled["hcm"])
                    if r["method"] in ("climate_zscore", "rolling_24h", "rolling_168h", "iqr")]
            print(f"\n=== Độ nhạy k = {kk}: nắng nóng temperature")
            print_table(rows, 10)


if __name__ == "__main__":
    main()

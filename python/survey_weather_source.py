"""Weather Data Source Survey for Open-Meteo (Roadmap P2).

Fetches a small sample of real hourly weather data for Ho Chi Minh City and Hanoi
from the Open-Meteo Forecast API and Historical (Archive) API, then prints the
structure needed before designing the InfluxDB schema:
- field list, JSON value types, units
- source timezone / timestamp format, resolution
- requested vs. grid-snapped coordinates, elevation
- how missing values are represented (probed via the ERA5-only archive model)

This script is read-only: it does NOT write anything to InfluxDB.
Uses only the Python standard library (no API key required).
"""

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

# Reconfigure stdout/stderr to UTF-8 (Windows console prints °C and Vietnamese text)
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


from open_meteo import ARCHIVE_URL, FORECAST_URL, LOCATIONS, fetch_json

# Survey also inspects surface_pressure, which the agreed schema leaves out
HOURLY_VARIABLES: List[str] = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "precipitation",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "weather_code",
]

# Common query parameters: metric units, UTC unix timestamps (unambiguous)
COMMON_PARAMS: Dict[str, str] = {
    "hourly": ",".join(HOURLY_VARIABLES),
    "temperature_unit": "celsius",
    "wind_speed_unit": "ms",
    "precipitation_unit": "mm",
    "timeformat": "unixtime",
    "timezone": "GMT",
}


def to_records(payload: Dict[str, Any], limit: int | None = None) -> List[Dict[str, Any]]:
    """Convert Open-Meteo column-oriented 'hourly' block into row records with UTC datetimes."""
    hourly = payload["hourly"]
    rows: List[Dict[str, Any]] = []
    for i, ts in enumerate(hourly["time"]):
        row: Dict[str, Any] = {"time": datetime.fromtimestamp(ts, tz=timezone.utc)}
        for var in HOURLY_VARIABLES:
            row[var] = hourly[var][i]
        rows.append(row)
    return rows[-limit:] if limit else rows


def summarize_fields(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-field summary: unit, observed JSON types, null count, min/max of the sample."""
    hourly, units = payload["hourly"], payload["hourly_units"]
    summary = []
    for var in HOURLY_VARIABLES:
        values = hourly[var]
        present = [v for v in values if v is not None]
        summary.append({
            "field": var,
            "unit": units.get(var, "?"),
            "json_types": sorted({type(v).__name__ for v in values}),
            "nulls": len(values) - len(present),
            "total": len(values),
            "min": min(present) if present else None,
            "max": max(present) if present else None,
        })
    return summary


def print_metadata(label: str, loc: Dict[str, Any], payload: Dict[str, Any]) -> None:
    times = payload["hourly"]["time"]
    step = times[1] - times[0] if len(times) > 1 else None
    print(f"\n[INFO] {label} — {loc['name']}")
    print(f"  Requested coords : {loc['latitude']}, {loc['longitude']}")
    print(f"  Grid-snapped     : {payload['latitude']}, {payload['longitude']} (elevation {payload['elevation']} m)")
    print(f"  Timezone         : {payload['timezone']} (utc_offset_seconds={payload['utc_offset_seconds']})")
    print(f"  Time format      : {payload['hourly_units']['time']} (raw example: {times[0]})")
    print(f"  Resolution       : {step} s between rows | rows returned: {len(times)}")
    print(f"  UTC range        : {datetime.fromtimestamp(times[0], tz=timezone.utc).isoformat()}"
          f" .. {datetime.fromtimestamp(times[-1], tz=timezone.utc).isoformat()}")


def print_field_table(summary: List[Dict[str, Any]]) -> None:
    print(f"  {'field':22s} {'unit':6s} {'json type':12s} {'nulls':>9s} {'min':>8s} {'max':>8s}")
    for s in summary:
        print(f"  {s['field']:22s} {s['unit']:6s} {','.join(s['json_types']):12s} "
              f"{s['nulls']:>4d}/{s['total']:<4d} {str(s['min']):>8s} {str(s['max']):>8s}")


def print_sample_rows(rows: List[Dict[str, Any]]) -> None:
    short = {"temperature_2m": "temp", "relative_humidity_2m": "rh", "dew_point_2m": "dew",
             "precipitation": "prcp", "pressure_msl": "p_msl", "surface_pressure": "p_sfc",
             "cloud_cover": "cloud", "wind_speed_10m": "wspd", "wind_direction_10m": "wdir",
             "wind_gusts_10m": "gust", "weather_code": "code"}
    header = f"  {'time (UTC)':20s}" + "".join(f"{short[v]:>8s}" for v in HOURLY_VARIABLES)
    print(header)
    for r in rows:
        print(f"  {r['time'].strftime('%Y-%m-%d %H:%M'):20s}"
              + "".join(f"{str(r[v]):>8s}" for v in HOURLY_VARIABLES))


def probe_missing_values(loc: Dict[str, Any], days: int) -> None:
    """Request ERA5 only (5-day publication delay) up to yesterday to observe how gaps look."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    params = {**COMMON_PARAMS, "latitude": loc["latitude"], "longitude": loc["longitude"],
              "start_date": start.isoformat(), "end_date": end.isoformat(), "models": "era5"}
    payload = fetch_json(ARCHIVE_URL, params)
    temps = payload["hourly"]["temperature_2m"]
    null_idx = [i for i, v in enumerate(temps) if v is None]
    print(f"\n[INFO] Missing-value probe — Archive API, models=era5, {start} .. {end}, {loc['name']}")
    if null_idx:
        first = datetime.fromtimestamp(payload["hourly"]["time"][null_idx[0]], tz=timezone.utc)
        print(f"  temperature_2m: {len(null_idx)}/{len(temps)} values are JSON null "
              f"(Python None), first gap at {first.isoformat()}")
        print(f"  Raw tail: {temps[-3:]}")
    else:
        print(f"  No nulls in this window ({len(temps)} values).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Survey Open-Meteo weather data structure (read-only).")
    parser.add_argument("--rows", type=int, default=12, help="Sample rows to print per location (default: 12)")
    parser.add_argument("--archive-days", type=int, default=3,
                        help="Days of archive (historical) data to fetch, ending 7 days ago (default: 3)")
    parser.add_argument("--probe-days", type=int, default=8,
                        help="Window for the ERA5 missing-value probe, ending yesterday (default: 8)")
    args = parser.parse_args()

    archive_end = date.today() - timedelta(days=7)
    archive_start = archive_end - timedelta(days=args.archive_days - 1)

    try:
        for key, loc in LOCATIONS.items():
            coords = {"latitude": loc["latitude"], "longitude": loc["longitude"]}

            # 1) Forecast API: recent past hours (near real-time) + 15-minutely "current" block
            fc = fetch_json(FORECAST_URL, {**COMMON_PARAMS, **coords, "past_days": 1, "forecast_days": 1,
                                           "current": ",".join(HOURLY_VARIABLES)})
            print("=" * 100)
            print_metadata("Forecast API (/v1/forecast, past_days=1)", loc, fc)
            print_field_table(summarize_fields(fc))
            now = datetime.now(timezone.utc)
            past_rows = [r for r in to_records(fc) if r["time"] <= now]
            print(f"\n  Last {args.rows} observed hours (time <= now):")
            print_sample_rows(past_rows[-args.rows:])
            cur = fc.get("current", {})
            print(f"\n  'current' block: time={datetime.fromtimestamp(cur['time'], tz=timezone.utc).isoformat()} "
                  f"interval={cur.get('interval')} s, temperature_2m={cur.get('temperature_2m')}")

            # 2) Archive API: historical reanalysis (best_match = IFS HRES + ERA5 + ERA5-Land)
            ar = fetch_json(ARCHIVE_URL, {**COMMON_PARAMS, **coords,
                                          "start_date": archive_start.isoformat(),
                                          "end_date": archive_end.isoformat()})
            print_metadata(f"Archive API (/v1/archive, {archive_start} .. {archive_end})", loc, ar)
            print_field_table(summarize_fields(ar))

        # 3) Missing-value representation
        probe_missing_values(LOCATIONS["hanoi"], args.probe_days)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n[INFO] Survey completed. Nothing was written to InfluxDB.")


if __name__ == "__main__":
    main()

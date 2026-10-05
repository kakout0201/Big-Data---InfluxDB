"""Unit tests for the weather cleaning pipeline and schema mapping (no network, no database).

Run: python python/test_weather_cleaning.py
"""

import sys
from datetime import date, datetime, timezone

from open_meteo import EXPECTED_UNITS, FIELD_MAP
from weather_cleaning import (
    CleaningReport,
    cast_types,
    check_ranges,
    clean_payload,
    deduplicate,
    drop_covered_by_archive,
    drop_empty,
    drop_future,
    validate_payload,
    validate_units,
)
from weather_collector import date_chunks
from weather_schema import to_point

T0 = 1725688800  # 2024-09-07T06:00:00Z (Typhoon Yagi landfall day)
NOW = datetime(2024, 9, 7, 8, 30, tzinfo=timezone.utc)


def make_payload(n: int = 3, start: int = T0) -> dict:
    """Synthetic Open-Meteo payload with valid values shaped exactly like the real API."""
    sample = {
        "temperature_2m": 26.4, "relative_humidity_2m": 91, "dew_point_2m": 24.8,
        "precipitation": 12.5, "pressure_msl": 985.2, "cloud_cover": 100,
        "wind_speed_10m": 18.3, "wind_direction_10m": 95, "wind_gusts_10m": 33.0,
        "weather_code": 63,
    }
    return {
        "utc_offset_seconds": 0,
        "hourly_units": dict(EXPECTED_UNITS),
        "hourly": {
            "time": [start + 3600 * i for i in range(n)],
            **{var: [sample[var]] * n for var in FIELD_MAP},
        },
    }


def expect_value_error(fn, *args) -> None:
    try:
        fn(*args)
    except ValueError:
        return
    raise AssertionError(f"{fn.__name__} should raise ValueError")


def test_parse_and_cast_types():
    records, report = clean_payload(make_payload(n=2), "hanoi", "archive", NOW)
    r = records[0]
    assert r["time"] == datetime(2024, 9, 7, 6, tzinfo=timezone.utc), r["time"]
    assert r["time"].tzinfo == timezone.utc
    assert r["location"] == "hanoi" and r["data_source"] == "archive"
    assert isinstance(r["humidity_pct"], float) and r["humidity_pct"] == 91.0
    assert isinstance(r["cloud_cover_pct"], float) and isinstance(r["wind_direction_deg"], float)
    assert isinstance(r["weather_code"], int) and r["weather_code"] == 63
    assert report.rows_in == 2 and report.rows_out == 2
    print("[PASS] parse: unix seconds -> UTC datetime; int fields cast to float, weather_code stays int")


def test_nulls_are_counted_and_empty_rows_dropped():
    payload = make_payload(n=3)
    payload["hourly"]["temperature_2m"][0] = None           # one missing value
    for var in FIELD_MAP:                                    # one fully missing hour (ERA5 delay)
        payload["hourly"][var][2] = None
    records, report = clean_payload(payload, "hcm", "archive", NOW)
    assert len(records) == 2, len(records)
    assert records[0]["temperature_c"] is None
    assert report.null_values["temperature_c"] == 2          # row 0 + row 2
    assert report.empty_rows_dropped == 1
    assert "temperature_c" not in to_point(records[0]).to_line_protocol()
    print("[PASS] nulls: counted per field, omitted from the point, all-null rows dropped")


def test_range_checks_keep_extremes_remove_impossible():
    report = CleaningReport()
    record = {"humidity_pct": 120.0, "temperature_c": 45.0, "precipitation_mm": 150.0,
              "pressure_msl_hpa": 950.0, "wind_gusts_ms": 60.0, "wind_speed_ms": -1.0,
              "weather_code": 42}
    out = check_ranges(record, report)
    assert out["humidity_pct"] is None and out["wind_speed_ms"] is None and out["weather_code"] is None
    # Rare but physically possible values are anomalies to detect later, not errors to clean
    assert out["temperature_c"] == 45.0 and out["precipitation_mm"] == 150.0
    assert out["pressure_msl_hpa"] == 950.0 and out["wind_gusts_ms"] == 60.0
    assert report.out_of_range_values == {"humidity_pct": 1, "wind_speed_ms": 1, "weather_code": 1}
    print("[PASS] ranges: impossible values removed, typhoon-level extremes kept")


def test_invalid_types_removed():
    report = CleaningReport()
    record = {"temperature_c": "abc", "humidity_pct": True, "dew_point_c": float("nan"),
              "weather_code": 2.5, "precipitation_mm": 0}
    out = cast_types(record, report)
    assert out["temperature_c"] is None and out["humidity_pct"] is None
    assert out["dew_point_c"] is None and out["weather_code"] is None
    assert out["precipitation_mm"] == 0.0 and isinstance(out["precipitation_mm"], float)
    assert sum(report.invalid_type_values.values()) == 4
    print("[PASS] types: strings, booleans, NaN and non-integer codes removed and counted")


def test_drop_future():
    payload = make_payload(n=5)                               # 06:00 .. 10:00, now = 08:30
    records, report = clean_payload(payload, "hcm", "forecast", NOW)
    assert [r["time"].hour for r in records] == [6, 7, 8]
    assert report.future_rows_dropped == 2
    print("[PASS] future: forecast hours after 'now' dropped")


def test_deduplicate_last_wins_and_sorted():
    report = CleaningReport()
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"location": "hcm", "time": t2, "temperature_c": 1.0},
        {"location": "hcm", "time": t, "temperature_c": 2.0},
        {"location": "hcm", "time": t2, "temperature_c": 3.0},
        {"location": "hanoi", "time": t2, "temperature_c": 4.0},
    ]
    out = deduplicate(rows, report)
    assert report.duplicate_rows_dropped == 1
    assert [(r["location"], r["time"], r["temperature_c"]) for r in out] == [
        ("hanoi", t2, 4.0), ("hcm", t, 2.0), ("hcm", t2, 3.0)]
    assert drop_empty([{"temperature_c": None, "weather_code": None}], report) == []
    print("[PASS] dedup: one row per (location, time), last wins, sorted")


def test_payload_and_unit_validation():
    bad_units = make_payload()
    bad_units["hourly_units"]["wind_speed_10m"] = "km/h"
    expect_value_error(validate_units, bad_units)
    local_time = make_payload()
    local_time["utc_offset_seconds"] = 25200
    expect_value_error(validate_payload, local_time)
    short_col = make_payload()
    short_col["hourly"]["pressure_msl"].pop()
    expect_value_error(validate_payload, short_col)
    missing = make_payload()
    del missing["hourly"]["weather_code"]
    expect_value_error(validate_payload, missing)
    expect_value_error(clean_payload, make_payload(), "hcm", "satellite", NOW)
    print("[PASS] validation: wrong units, non-UTC, ragged columns, missing variable, bad source rejected")


def test_forecast_never_overwrites_archive():
    records, report = clean_payload(make_payload(n=3), "hcm", "forecast", NOW)
    cutoff = datetime(2024, 9, 7, 7, tzinfo=timezone.utc)
    kept = drop_covered_by_archive(records, cutoff, report)
    assert [r["time"].hour for r in kept] == [8]
    assert report.archive_covered_rows_dropped == 2 and report.rows_out == 1
    assert drop_covered_by_archive(records, None, CleaningReport()) == records
    print("[PASS] precedence: forecast rows at/before the archive cutoff are skipped")


def test_line_protocol():
    records, _ = clean_payload(make_payload(n=1), "danang", "archive", NOW)
    lp = to_point(records[0]).to_line_protocol()
    assert lp.startswith("weather_hourly,location=danang "), lp
    assert "humidity_pct=91," in lp and "humidity_pct=91i" not in lp     # float, not integer
    assert "weather_code=63i" in lp                                      # integer field
    assert 'data_source="archive"' in lp                                 # string field
    assert lp.endswith(f" {T0 * 10**9}"), lp                             # ns timestamp
    print("[PASS] line protocol: float/int/string field types and ns timestamp correct")


def test_date_chunks():
    chunks = date_chunks(date(2024, 1, 1), date(2026, 10, 5), 365)
    assert chunks[0][0] == date(2024, 1, 1) and chunks[-1][1] == date(2026, 10, 5)
    for (a_start, a_end), (b_start, _) in zip(chunks, chunks[1:]):
        assert (b_start - a_end).days == 1 and a_start <= a_end   # contiguous, no overlap
    assert date_chunks(date(2024, 1, 1), date(2024, 1, 1), 30) == [(date(2024, 1, 1), date(2024, 1, 1))]
    expect_value_error(date_chunks, date(2024, 1, 2), date(2024, 1, 1), 30)
    print("[PASS] chunks: contiguous inclusive date ranges without gaps or overlap")


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print("=" * 70)
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"[FAIL] {test.__name__}: {exc}")
    print("=" * 70)
    print(f"{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

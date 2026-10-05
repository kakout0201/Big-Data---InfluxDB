"""Cleaning / transformation of Open-Meteo payloads before ingestion (Roadmap P4).

Every step is a pure function (no network, no database) so it can be unit-tested,
and every step records what it changed in a CleaningReport for the project report.

Pipeline (clean_payload):
  1. validate_payload  - structure, UTC offset, column lengths
  2. validate_units    - units must match what was requested (metric, unixtime)
  3. parse_records     - unix seconds -> UTC datetime, rename to schema field names
  4. drop_future       - forecast hours later than "now" are not observations yet
  5. cast_types        - 9 measurements -> float, weather_code -> int; non-numeric -> None
  6. check_ranges      - physically impossible values -> None (rare extremes are KEPT)
  7. deduplicate       - one record per (location, time), last one wins
  8. drop_empty        - records with no measurement left are dropped

Missing values (JSON null) are not invented or interpolated: the field is simply
omitted from the InfluxDB point, and the count is reported.
"""

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from open_meteo import EXPECTED_UNITS, FIELD_MAP
from weather_schema import (
    DATA_SOURCE_FIELD,
    DATA_SOURCES,
    FLOAT_FIELDS,
    INTEGER_FIELDS,
    LOCATION_TAG,
    MEASUREMENT_FIELDS,
    PHYSICAL_RANGES,
    VALID_WEATHER_CODES,
)

Record = Dict[str, Any]


@dataclass
class CleaningReport:
    """Counters describing what each cleaning step changed."""

    rows_in: int = 0
    future_rows_dropped: int = 0
    duplicate_rows_dropped: int = 0
    empty_rows_dropped: int = 0
    archive_covered_rows_dropped: int = 0
    rows_out: int = 0
    null_values: Counter = field(default_factory=Counter)
    invalid_type_values: Counter = field(default_factory=Counter)
    out_of_range_values: Counter = field(default_factory=Counter)

    def merge(self, other: "CleaningReport") -> None:
        """Accumulate another report (e.g. from the next chunk or location) into this one."""
        self.rows_in += other.rows_in
        self.future_rows_dropped += other.future_rows_dropped
        self.duplicate_rows_dropped += other.duplicate_rows_dropped
        self.empty_rows_dropped += other.empty_rows_dropped
        self.archive_covered_rows_dropped += other.archive_covered_rows_dropped
        self.rows_out += other.rows_out
        self.null_values.update(other.null_values)
        self.invalid_type_values.update(other.invalid_type_values)
        self.out_of_range_values.update(other.out_of_range_values)

    def format_lines(self) -> List[str]:
        def counter_text(c: Counter) -> str:
            return ", ".join(f"{k}={v}" for k, v in sorted(c.items())) if c else "none"

        return [
            f"rows in                      : {self.rows_in}",
            f"future rows dropped          : {self.future_rows_dropped}",
            f"duplicate rows dropped       : {self.duplicate_rows_dropped}",
            f"empty rows dropped           : {self.empty_rows_dropped}",
            f"rows already in archive      : {self.archive_covered_rows_dropped}",
            f"rows out                     : {self.rows_out}",
            f"null values from source      : {counter_text(self.null_values)}",
            f"invalid-type values removed  : {counter_text(self.invalid_type_values)}",
            f"out-of-range values removed  : {counter_text(self.out_of_range_values)}",
        ]


def validate_payload(payload: Dict[str, Any]) -> None:
    """Check the payload shape. Raises ValueError on anything that would corrupt timestamps."""
    if "hourly" not in payload or "hourly_units" not in payload:
        raise ValueError("Payload has no 'hourly' / 'hourly_units' block")
    if payload.get("utc_offset_seconds", 0) != 0:
        raise ValueError(f"Expected UTC data, got utc_offset_seconds={payload['utc_offset_seconds']}")
    hourly = payload["hourly"]
    if "time" not in hourly:
        raise ValueError("Payload has no 'hourly.time' column")
    missing = [var for var in FIELD_MAP if var not in hourly]
    if missing:
        raise ValueError(f"Payload is missing variables: {missing}")
    n = len(hourly["time"])
    bad = {var: len(hourly[var]) for var in FIELD_MAP if len(hourly[var]) != n}
    if bad:
        raise ValueError(f"Column length mismatch (time has {n}): {bad}")


def validate_units(payload: Dict[str, Any]) -> None:
    """Units are fixed by the request; any difference means the request or API changed."""
    units = payload["hourly_units"]
    wrong = {k: units.get(k) for k, expected in EXPECTED_UNITS.items() if units.get(k) != expected}
    if wrong:
        raise ValueError(f"Unexpected units {wrong}; expected {EXPECTED_UNITS}")


def parse_records(payload: Dict[str, Any], location: str, data_source: str) -> List[Record]:
    """Convert column-oriented 'hourly' arrays to row records with UTC datetimes and schema names."""
    if data_source not in DATA_SOURCES:
        raise ValueError(f"data_source must be one of {DATA_SOURCES}, got {data_source!r}")
    hourly = payload["hourly"]
    records: List[Record] = []
    for i, ts in enumerate(hourly["time"]):
        if isinstance(ts, bool) or not isinstance(ts, int):
            raise ValueError(f"Non-integer unix timestamp at row {i}: {ts!r}")
        record: Record = {
            "time": datetime.fromtimestamp(ts, tz=timezone.utc),
            LOCATION_TAG: location,
            DATA_SOURCE_FIELD: data_source,
        }
        for source_name, field_name in FIELD_MAP.items():
            record[field_name] = hourly[source_name][i]
        records.append(record)
    return records


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _to_int(value: Any) -> Optional[int]:
    as_float = _to_float(value)
    if as_float is None or not as_float.is_integer():
        return None
    return int(as_float)


def cast_types(record: Record, report: CleaningReport) -> Record:
    """Measurements -> float, weather_code -> int. JSON null stays None (counted as null)."""
    out = dict(record)
    for name in MEASUREMENT_FIELDS:
        raw = record.get(name)
        if raw is None:
            report.null_values[name] += 1
            continue
        converted = _to_int(raw) if name in INTEGER_FIELDS else _to_float(raw)
        if converted is None:
            report.invalid_type_values[name] += 1
        out[name] = converted
    return out


def check_ranges(record: Record, report: CleaningReport) -> Record:
    """Physically impossible values -> None. Bounds are in weather_schema.PHYSICAL_RANGES."""
    out = dict(record)
    for name, (low, high) in PHYSICAL_RANGES.items():
        value = out.get(name)
        if value is not None and not (low <= value <= high):
            report.out_of_range_values[name] += 1
            out[name] = None
    code = out.get("weather_code")
    if code is not None and code not in VALID_WEATHER_CODES:
        report.out_of_range_values["weather_code"] += 1
        out["weather_code"] = None
    return out


def drop_future(records: List[Record], now: datetime, report: CleaningReport) -> List[Record]:
    """Keep only hours that have already started (time <= now)."""
    kept = [r for r in records if r["time"] <= now]
    report.future_rows_dropped += len(records) - len(kept)
    return kept


def deduplicate(records: List[Record], report: CleaningReport) -> List[Record]:
    """One record per (location, time); the last occurrence wins. Output is time-sorted."""
    by_key: Dict[Tuple[str, datetime], Record] = {}
    for r in records:
        by_key[(r[LOCATION_TAG], r["time"])] = r
    report.duplicate_rows_dropped += len(records) - len(by_key)
    return sorted(by_key.values(), key=lambda r: (r[LOCATION_TAG], r["time"]))


def drop_empty(records: List[Record], report: CleaningReport) -> List[Record]:
    """Drop records where every measurement is None (nothing worth storing)."""
    kept = [r for r in records if any(r.get(name) is not None for name in MEASUREMENT_FIELDS)]
    report.empty_rows_dropped += len(records) - len(kept)
    return kept


def drop_covered_by_archive(
    records: List[Record], archive_cutoff: Optional[datetime], report: CleaningReport
) -> List[Record]:
    """Forecast data must never overwrite archive data: keep only hours after the archive cutoff."""
    if archive_cutoff is None:
        return records
    kept = [r for r in records if r["time"] > archive_cutoff]
    report.archive_covered_rows_dropped += len(records) - len(kept)
    report.rows_out -= len(records) - len(kept)
    return kept


def clean_payload(
    payload: Dict[str, Any], location: str, data_source: str, now: datetime
) -> Tuple[List[Record], CleaningReport]:
    """Run the full cleaning pipeline on one Open-Meteo payload for one location."""
    report = CleaningReport()
    validate_payload(payload)
    validate_units(payload)
    records = parse_records(payload, location, data_source)
    report.rows_in = len(records)
    records = drop_future(records, now, report)
    records = [check_ranges(cast_types(r, report), report) for r in records]
    records = deduplicate(records, report)
    records = drop_empty(records, report)
    report.rows_out = len(records)
    return records, report

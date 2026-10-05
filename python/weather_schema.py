"""InfluxDB 3 schema for the weather pipeline (agreed in Roadmap P2, see CLAUDE.md "Data Model").

Database : weather (override with WEATHER_INFLUXDB_DATABASE or --database)
Table    : weather_hourly
Tag      : location            hcm | hanoi | danang
Time     : start of the hour, UTC, nanosecond precision
Fields   : 9 float measurements, weather_code (integer), data_source (string)

Overwrite rule: (table, location, time) identifies a point, so a later write for the
same hour replaces the field values. Archive data is written over forecast data.
"""

from typing import Any, Dict, FrozenSet, Tuple

from influxdb_client_3 import Point

DEFAULT_DATABASE = "weather"
TABLE = "weather_hourly"
LOCATION_TAG = "location"

FLOAT_FIELDS: Tuple[str, ...] = (
    "temperature_c",
    "humidity_pct",
    "dew_point_c",
    "precipitation_mm",
    "pressure_msl_hpa",
    "cloud_cover_pct",
    "wind_speed_ms",
    "wind_direction_deg",
    "wind_gusts_ms",
)
INTEGER_FIELDS: Tuple[str, ...] = ("weather_code",)
MEASUREMENT_FIELDS: Tuple[str, ...] = FLOAT_FIELDS + INTEGER_FIELDS

DATA_SOURCE_FIELD = "data_source"
DATA_SOURCES: Tuple[str, ...] = ("forecast", "archive")

# Physically possible bounds (inclusive). Values outside are data errors, not anomalies:
# rare-but-possible extremes (heatwaves, typhoon winds, torrential rain) stay inside these
# bounds on purpose so that anomaly detection can still see them.
PHYSICAL_RANGES: Dict[str, Tuple[float, float]] = {
    "temperature_c": (-40.0, 60.0),        # world record max 56.7 °C
    "humidity_pct": (0.0, 100.0),
    "dew_point_c": (-60.0, 40.0),
    "precipitation_mm": (0.0, 400.0),      # world record 1-hour total ≈ 305 mm
    "pressure_msl_hpa": (870.0, 1085.0),   # world records 870 / 1084.8 hPa
    "cloud_cover_pct": (0.0, 100.0),
    "wind_speed_ms": (0.0, 120.0),
    "wind_direction_deg": (0.0, 360.0),
    "wind_gusts_ms": (0.0, 120.0),         # world record gust ≈ 113 m/s
}

# WMO weather interpretation codes used by Open-Meteo
VALID_WEATHER_CODES: FrozenSet[int] = frozenset({
    0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67,
    71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99,
})


def to_point(record: Dict[str, Any]) -> Point:
    """Build an InfluxDB Point from a cleaned record; None-valued fields are omitted."""
    point = Point(TABLE).tag(LOCATION_TAG, record["location"])
    for name in FLOAT_FIELDS:
        if record.get(name) is not None:
            point = point.field(name, float(record[name]))
    for name in INTEGER_FIELDS:
        if record.get(name) is not None:
            point = point.field(name, int(record[name]))
    point = point.field(DATA_SOURCE_FIELD, record[DATA_SOURCE_FIELD])
    return point.time(record["time"])

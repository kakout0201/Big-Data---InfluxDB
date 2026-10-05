"""Open-Meteo API client (I/O layer) for the weather pipeline.

Wraps the two endpoints used by the project:
- Forecast API (/v1/forecast): recent hours, used for near real-time collection.
- Archive API  (/v1/archive):  historical reanalysis, used for backfill.

Requests are made in metric units with UTC unix timestamps so that the
cleaning layer never has to guess a timezone. No API key is required.
Data licence: CC BY 4.0 (attribution: "Weather data by Open-Meteo.com").
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Dict, List

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# City-centre coordinates; Open-Meteo snaps them to the nearest model grid cell.
LOCATIONS: Dict[str, Dict[str, Any]] = {
    "hcm": {"name": "TP. Hồ Chí Minh", "latitude": 10.8231, "longitude": 106.6297},
    "hanoi": {"name": "Hà Nội", "latitude": 21.0285, "longitude": 105.8542},
    "danang": {"name": "Đà Nẵng", "latitude": 16.0544, "longitude": 108.2022},
}

# Open-Meteo hourly variable -> InfluxDB field name (schema agreed in P2, see CLAUDE.md)
FIELD_MAP: Dict[str, str] = {
    "temperature_2m": "temperature_c",
    "relative_humidity_2m": "humidity_pct",
    "dew_point_2m": "dew_point_c",
    "precipitation": "precipitation_mm",
    "pressure_msl": "pressure_msl_hpa",
    "cloud_cover": "cloud_cover_pct",
    "wind_speed_10m": "wind_speed_ms",
    "wind_direction_10m": "wind_direction_deg",
    "wind_gusts_10m": "wind_gusts_ms",
    "weather_code": "weather_code",
}

# Units Open-Meteo must report back for the request parameters below
EXPECTED_UNITS: Dict[str, str] = {
    "time": "unixtime",
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "dew_point_2m": "°C",
    "precipitation": "mm",
    "pressure_msl": "hPa",
    "cloud_cover": "%",
    "wind_speed_10m": "m/s",
    "wind_direction_10m": "°",
    "wind_gusts_10m": "m/s",
    "weather_code": "wmo code",
}

COMMON_PARAMS: Dict[str, str] = {
    "hourly": ",".join(FIELD_MAP),
    "temperature_unit": "celsius",
    "wind_speed_unit": "ms",
    "precipitation_unit": "mm",
    "timeformat": "unixtime",
    "timezone": "GMT",
}

RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def fetch_json(
    base_url: str,
    params: Dict[str, Any],
    timeout: float = 60.0,
    retries: int = 3,
    backoff_seconds: float = 2.0,
) -> Dict[str, Any]:
    """GET an Open-Meteo endpoint and return the decoded JSON payload.

    Retries on network errors, HTTP 429 and 5xx with exponential backoff.

    Raises:
        RuntimeError: When the request keeps failing or the API answers {"error": true}.
    """
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                payload = json.load(resp)
            break
        except urllib.error.HTTPError as exc:
            try:
                reason = json.load(exc).get("reason", "")
            except Exception:
                reason = ""
            last_error = f"HTTP {exc.code} {reason}".strip()
            if exc.code not in RETRYABLE_HTTP_CODES:
                raise RuntimeError(f"API error from {base_url}: {last_error}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = f"network error: {getattr(exc, 'reason', exc)}"
        if attempt < retries:
            time.sleep(backoff_seconds * 2 ** (attempt - 1))
    else:
        raise RuntimeError(f"Cannot fetch {base_url} after {retries} attempts ({last_error})")

    if payload.get("error"):
        raise RuntimeError(f"API error from {base_url}: {payload.get('reason')}")
    return payload


def fetch_archive(location_key: str, start: date, end: date) -> Dict[str, Any]:
    """Historical hourly data (best_match = ECMWF IFS + ERA5 + ERA5-Land), inclusive dates."""
    loc = LOCATIONS[location_key]
    params = {
        **COMMON_PARAMS,
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    return fetch_json(ARCHIVE_URL, params)


def fetch_forecast(location_key: str, past_days: int) -> Dict[str, Any]:
    """Hourly data for the last `past_days` days plus today (future hours are dropped by cleaning)."""
    loc = LOCATIONS[location_key]
    params = {
        **COMMON_PARAMS,
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "past_days": past_days,
        "forecast_days": 1,
    }
    return fetch_json(FORECAST_URL, params)


def parse_location_keys(value: str) -> List[str]:
    """Parse a comma-separated location list ('all' = every configured location)."""
    if value.strip().lower() == "all":
        return list(LOCATIONS)
    keys = [k.strip().lower() for k in value.split(",") if k.strip()]
    unknown = [k for k in keys if k not in LOCATIONS]
    if unknown:
        raise ValueError(f"Unknown location(s): {unknown}. Valid: {list(LOCATIONS)}")
    return keys

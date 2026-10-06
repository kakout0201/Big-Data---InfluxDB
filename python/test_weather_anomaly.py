"""Unit tests for weather_anomaly (pure numpy; no network, no database).

Run: python python/test_weather_anomaly.py
"""

import sys

import numpy as np

# Reconfigure stdout to UTF-8 (Windows console; test messages contain σ and Vietnamese text)
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from weather_anomaly import (
    BOTH,
    beaufort_level,
    gust_severity,
    heat_severity,
    rain_24h_severity,
    rolling_max,
    zscore_severity,
    HIGH,
    LOW,
    climate_zscore,
    confusion,
    count_episodes,
    event_metrics,
    global_zscore,
    inject_anomalies,
    iqr_detect,
    local_calendar,
    persistent_climate_zscore,
    pressure_tendency,
    rolling_sum,
    rolling_zscore,
    stuck_detect,
    threshold_detect,
)


def hourly(start: str, end: str) -> np.ndarray:
    return np.arange(np.datetime64(start, "h"), np.datetime64(end, "h")).astype("datetime64[s]")


def expect_value_error(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError(f"{fn.__name__} should raise ValueError")


def test_local_calendar():
    t = np.array(["2024-01-31T17:00:00", "2024-12-31T16:59:59"], dtype="datetime64[s]")
    years, months, hours = local_calendar(t)
    assert list(years) == [2024, 2024] and list(months) == [2, 12] and list(hours) == [0, 23]
    print("[PASS] calendar: UTC 17:00 is local midnight of the next day (UTC+7)")


def test_threshold():
    det = threshold_detect([30.0, 35.0, 39.2, np.nan], 35.0, HIGH, "nắng nóng")
    assert det.flags.tolist() == [False, True, True, False]
    assert np.isclose(det.scores[2], 4.2)
    assert det.reason(2, 39.2, "°C") == "39.2°C ≥ ngưỡng 35.0°C (nắng nóng)"
    low = threshold_detect([1001.0, 995.0], 1000.0, LOW)
    assert low.flags.tolist() == [False, True]
    expect_value_error(threshold_detect, [1.0], 0.0, BOTH)
    print("[PASS] threshold: inclusive limit, NaN never flagged, reason text")


def test_global_zscore():
    x = np.r_[np.tile([10.0, 11.0, 9.0, 10.0], 50), 30.0]
    det = global_zscore(x, k=3.0)
    assert det.flags[-1] and det.flags.sum() == 1
    assert global_zscore(np.full(10, 5.0)).count == 0          # zero variance -> no flags
    assert global_zscore(x, k=3.0, direction=LOW).count == 0
    print("[PASS] global z: single outlier flagged; constant series and wrong direction give no flags")


def test_climate_zscore_ignores_daily_cycle_and_leaves_year_out():
    t = hourly("2024-01-01T00", "2027-01-01T00")
    _, months, hours = local_calendar(t)
    rng = np.random.default_rng(1)
    x = 10 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, 0.5, len(t))
    years, _, _ = local_calendar(t)
    april_2025 = (years == 2025) & (months == 4)
    x[april_2025] += 4.0                                        # sustained warm month
    clim = climate_zscore(t, x, k=3.0, direction=HIGH)
    glob = global_zscore(x, k=3.0, direction=HIGH)
    inside = clim.flags[april_2025].mean()
    outside = clim.flags[~april_2025].mean()
    assert inside > 0.9, inside                                 # whole month detected
    assert outside < 0.005, outside                             # daily cycle not flagged
    assert glob.flags[april_2025].mean() < 0.05                 # global z misses it (cycle dominates)
    # leave-one-year-out: April 2025 baseline must come from 2024 + 2026 only (≈ unshifted)
    i = np.flatnonzero(april_2025)[0]
    assert abs(clim.baseline[i] - 10 * np.sin(2 * np.pi * hours[i] / 24)) < 0.5
    # a cell present in one year only has no other-year baseline
    single = climate_zscore(t[:24 * 31], x[:24 * 31])
    assert np.isnan(single.scores).all() and single.count == 0
    print("[PASS] climate z: detects a sustained warm month, ignores the daily cycle, excludes own year")


def test_persistent_climate_zscore_catches_sustained_mild_anomaly():
    t = hourly("2024-01-01T00", "2027-01-01T00")
    years, months, hours = local_calendar(t)
    rng = np.random.default_rng(4)
    x = 10 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, 1.0, len(t))
    start = np.flatnonzero((years == 2025) & (months == 4))[0]
    spell = slice(start, start + 14 * 24)                        # 14 days, only +1.3σ per hour
    x[spell] += 1.3
    hourly_z = climate_zscore(t, x, k=3.0, direction=HIGH)
    persistent = persistent_climate_zscore(t, x, window=168, threshold=1.0, direction=HIGH)
    assert hourly_z.flags[spell].mean() < 0.15                  # hour-by-hour misses most of it
    second_half = slice(start + 8 * 24, start + 14 * 24)
    assert persistent.flags[second_half].mean() > 0.95          # sustained anomaly detected
    expected_zone = np.zeros(len(t), bool)
    expected_zone[start:start + 16 * 24] = True                 # spell + window lag
    assert persistent.flags[~expected_zone].mean() < 0.001
    i = start + 13 * 24
    assert np.isclose(persistent.observed[i], x[i - 167:i + 1].mean())   # trailing mean incl. current
    assert persistent.reason(i, x[i]).startswith("TB 168 giờ qua")
    assert np.isnan(persistent.scores[:167]).all()               # incomplete window
    print("[PASS] persistent climate z: catches a 14-day +1.3σ spell that hourly z misses")


def test_iqr_zero_inflated_rain():
    rng = np.random.default_rng(2)
    rain = np.zeros(1000)
    wet = rng.choice(np.r_[0:500, 501:1000], 200, replace=False)  # 80 % dry hours (>= 75 %)
    rain[wet] = rng.gamma(1.0, 2.0, 200)
    rain[500] = 80.0
    naive = iqr_detect(rain, k=3.0)                             # Q1 = Q3 = 0 -> IQR 0 -> unusable
    assert naive.count == 0 and np.isnan(naive.scores).all()
    wet_ref = iqr_detect(rain, k=3.0, reference_mask=rain >= 0.1)
    assert wet_ref.flags[500] and wet_ref.count < 20
    print("[PASS] iqr: all-hours reference collapses on zero-inflated rain; wet-hours reference works")


def test_iqr_groups_and_low():
    x = np.r_[np.linspace(0, 10, 100), np.linspace(1000, 1010, 100)]
    groups = np.r_[np.zeros(100), np.ones(100)]
    x[150] = 970.0
    det = iqr_detect(x, k=1.5, direction=LOW, groups=groups)
    assert det.flags[150] and det.count == 1                    # seasonal-style grouping
    expect_value_error(iqr_detect, x, direction=BOTH)
    print("[PASS] iqr: per-group fences and low direction")


def test_rolling_zscore_is_causal():
    rng = np.random.default_rng(3)
    x = 1000 + rng.normal(0, 1.0, 400)
    x[300] = 985.0
    det = rolling_zscore(x, window=24, k=3.0, direction=LOW)
    assert np.isnan(det.scores[:24]).all()                      # incomplete window
    assert det.flags[300] and det.scores[300] < -8
    assert not det.flags[301]                                   # spike is now inside the window
    # baseline of point i uses only points i-24 .. i-1
    assert np.isclose(det.baseline[300], x[276:300].mean())
    assert rolling_zscore(np.full(50, 3.0), window=24).count == 0   # std 0 -> no flags
    print("[PASS] rolling z: trailing window excludes the current point; zero-variance safe")


def test_pressure_tendency():
    x = np.r_[np.full(10, 1005.0), 1005.0 - 2.0 * np.arange(1, 6)]
    det = pressure_tendency(x, hours=3, threshold=-3.0)
    assert det.flags.tolist() == [False] * 10 + [False, True, True, True, True]
    assert np.isclose(det.scores[13], -6.0) and np.isclose(det.baseline[13], 1003.0)
    print("[PASS] tendency: flags falls of >= 3 hPa in 3 h")


def test_stuck_detect():
    x = np.r_[np.arange(5.0), np.full(8, 7.0), np.arange(5.0), np.full(5, 1.0), np.nan, np.full(3, 1.0)]
    det = stuck_detect(x, min_run=6)
    assert det.flags[5:13].all() and det.count == 8
    assert det.scores[5] == 8
    print("[PASS] stuck: run of 8 flagged, run of 5 and NaN-broken runs not flagged")


def test_severity_labels():
    assert beaufort_level(10.7) == 0 and beaufort_level(17.2) == 8 and beaufort_level(32.4) == 11
    assert gust_severity(32.4) == "gió giật cấp 11" and gust_severity(5.0) == "gió giật dưới cấp 6"
    assert [rain_24h_severity(v) for v in (10, 16, 50, 100)] == ["mưa nhỏ", "mưa vừa", "mưa to", "mưa rất to"]
    assert [heat_severity(v) for v in (34.9, 35, 37.5, 39.2)] == [
        "ấm bất thường kéo dài", "nắng nóng", "nắng nóng gay gắt", "nắng nóng đặc biệt gay gắt"]
    assert [zscore_severity(v) for v in (-3.2, -4.0, -8.5)] == ["vừa", "mạnh", "rất mạnh"]
    out = rolling_max([1.0, 5.0, 2.0, 3.0], 2)
    assert np.isnan(out[0]) and out[1:].tolist() == [5.0, 5.0, 3.0]
    print("[PASS] severity: Beaufort gust levels, 24 h rain, heat 35/37/39 °C, z strength, rolling max")


def test_rolling_sum():
    out = rolling_sum([1.0, 2.0, 3.0, np.nan, 5.0, 6.0], 2)
    assert np.isnan(out[0]) and out[1:3].tolist() == [3.0, 5.0]
    assert np.isnan(out[3]) and np.isnan(out[4]) and out[5] == 11.0
    print("[PASS] rolling sum: trailing window including current point, NaN-aware")


def test_inject_anomalies():
    x = np.zeros(10000)
    a1, labels, kind = inject_anomalies(x, seed=7, n_spikes=10, spike_range=(5, 8),
                                        n_stuck=5, stuck_length=8)
    a2, labels2, _ = inject_anomalies(x, seed=7, n_spikes=10, spike_range=(5, 8),
                                      n_stuck=5, stuck_length=8)
    assert np.array_equal(a1, a2) and np.array_equal(labels, labels2)   # reproducible
    assert (kind == 1).sum() == 10 and (kind == 2).sum() == 40
    assert labels.sum() == 50 and not labels[:200].any() and not labels[-200:].any()
    spikes = np.abs(a1[kind == 1])
    assert ((spikes >= 5) & (spikes <= 8)).all()
    assert np.array_equal(x, np.zeros(10000))                  # input untouched
    expect_value_error(inject_anomalies, np.zeros(1000), 1, 10, (1, 2), 5, 8)
    print("[PASS] inject: reproducible, labelled, spaced, input not modified")


def test_metrics():
    c = confusion(np.array([1, 1, 0, 0, 1], bool), np.array([1, 0, 1, 0, 1], bool))
    assert (c["tp"], c["fp"], c["fn"]) == (2, 1, 1) and np.isclose(c["precision"], 2 / 3)
    t = hourly("2024-09-05T12", "2024-09-08T00")
    flags = np.zeros(len(t), bool)
    flags[[10, 20, 21]] = True
    m = event_metrics(t, flags, "2024-09-05T17:00", "2024-09-07T17:00", peak="2024-09-07T13:00")
    assert m["detected"] and m["flagged_hours"] == 3 and m["window_hours"] == 48
    assert m["first_flag"] == np.datetime64("2024-09-05T22:00", "s")
    assert m["lead_hours"] == 39.0 and m["flagged_days"] == 1
    f = np.zeros(100, bool)
    f[[3, 5, 9, 30, 31, 80]] = True
    assert count_episodes(f, max_gap=6) == 3 and count_episodes(np.zeros(5, bool)) == 0
    print("[PASS] metrics: confusion counts, event coverage, lead time, alarm episodes")


def main() -> None:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
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

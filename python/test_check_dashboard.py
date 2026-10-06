"""Unit tests for check_dashboard.py and the committed dashboard JSON (no Grafana, no database).

Run: python python/test_check_dashboard.py
"""

import json
import os
import sys

from check_dashboard import DEFAULT_DASHBOARD, interpolate, iter_targets, static_problems

DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", DEFAULT_DASHBOARD)


def load_dashboard() -> dict:
    with open(DASHBOARD_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def test_interpolate_variables_but_not_macros():
    sql = ("SELECT date_bin(INTERVAL '$time_bin', time) FROM t WHERE time >= $__timeFrom() "
           "AND location = '$location' AND field IN (${field:singlequote}) AND x = '$unknown'")
    out = interpolate(sql, {"location": "hanoi", "time_bin": "6h", "field": ["a", "b"]})
    assert "INTERVAL '6h'" in out and "location = 'hanoi'" in out, out
    assert "field IN ('a','b')" in out, out
    assert "$__timeFrom()" in out and "'$unknown'" in out, out          # Grafana macros / unknown vars kept
    print("[PASS] interpolate: $var, ${var:singlequote} replaced; $__macros and unknown vars untouched")


def test_static_rules_catch_missing_filters():
    panel = {"id": 1, "title": "p", "targets": [
        {"refId": "A", "datasource": {"uid": "influxdb3_weather"},
         "rawSql": "SELECT * FROM weather_hourly WHERE time >= $__timeFrom()"},
        {"refId": "B", "datasource": {"uid": "other"},
         "rawSql": "SELECT 1 WHERE time >= $__timeFrom() AND time <= $__timeTo() AND location = '$location'"}]}
    problems = static_problems({"panels": [panel, {**panel, "targets": []}]})
    assert any("duplicate panel ids" in p for p in problems), problems
    assert any("p / A: missing $__timeTo()" in p for p in problems), problems
    assert any("p / A: missing location = '$location'" in p for p in problems), problems
    assert any("p / B: datasource uid" in p for p in problems), problems
    print("[PASS] static rules: duplicate ids, wrong datasource and missing time/location filters reported")


def test_committed_dashboard_passes_static_rules():
    dashboard = load_dashboard()
    assert static_problems(dashboard) == [], static_problems(dashboard)
    assert dashboard["uid"] == "weather_analytics" and dashboard["timezone"] == "Asia/Ho_Chi_Minh"
    variables = {v["name"]: v for v in dashboard["templating"]["list"]}
    assert set(variables) == {"location", "time_bin", "field"}, set(variables)
    assert variables["location"]["current"]["value"] == "hcm"
    assert sum(1 for _ in iter_targets(dashboard)) >= 15
    assert all("--" not in t["rawSql"] for _, t in iter_targets(dashboard))   # one-line SQL: no comments
    print("[PASS] dashboard JSON: every query filtered by time range and $location; hcm default; no SQL comments")


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

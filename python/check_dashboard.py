"""Check the weather Grafana dashboard: static query rules + run every panel query through Grafana (Roadmap P8).

Static checks (no network): unique panel ids, every target uses the weather datasource and
filters on $__timeFrom(), $__timeTo() and location = '$location'.

Live checks: datasource health, then every target is sent to Grafana's /api/ds/query for each
scenario (dashboard variables are substituted here, Grafana macros are expanded by Grafana).
Reports rows and latency per panel; exit code 1 if any query fails or a static rule is broken.

Usage:
  python python/check_dashboard.py                    # static + live, all scenarios
  python python/check_dashboard.py --static-only
  python python/check_dashboard.py --scenarios yagi,heatwave
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterator, List, Tuple

# Reconfigure stdout/stderr to UTF-8 (Windows console prints Vietnamese text)
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

from run_sql import print_table

DEFAULT_DASHBOARD = os.path.join("grafana", "dashboards_json", "weather_analytics.json")
DATASOURCE_UID = "influxdb3_weather"
REQUIRED_FRAGMENTS = ("$__timeFrom()", "$__timeTo()", "location = '$location'")
ALL_FIELDS = ("temperature_c", "pressure_msl_hpa", "wind_gusts_ms", "rain_24h_mm")


@dataclass(frozen=True)
class Scenario:
    name: str
    location: str
    start: str          # ISO UTC or "now-<N>d"
    end: str
    time_bin: str       # what Grafana's auto interval would pick for this range


SCENARIOS = [
    Scenario("7d_hcm", "hcm", "now-7d", "now", "1h"),
    Scenario("7d_hanoi", "hanoi", "now-7d", "now", "1h"),
    Scenario("7d_danang", "danang", "now-7d", "now", "1h"),
    Scenario("yagi", "hanoi", "2024-09-05T17:00:00", "2024-09-09T17:00:00", "1h"),
    Scenario("heatwave", "hcm", "2024-03-31T17:00:00", "2024-04-30T17:00:00", "6h"),
    Scenario("1y_hcm", "hcm", "now-365d", "now", "1d"),
]


def iter_targets(dashboard: Dict) -> Iterator[Tuple[Dict, Dict]]:
    """Yield (panel, target) for every query target, including panels nested in collapsed rows."""
    for panel in dashboard.get("panels", []):
        for inner in [panel] + panel.get("panels", []):
            for tgt in inner.get("targets", []):
                yield inner, tgt


def interpolate(sql: str, variables: Dict[str, object]) -> str:
    """Substitute dashboard variables the way Grafana does for $name, ${name} and ${name:singlequote}."""
    def value(name: str, fmt: str) -> str:
        val = variables[name]
        if fmt == "singlequote":
            items = val if isinstance(val, (list, tuple)) else [val]
            return ",".join("'" + str(v).replace("'", "\\'") + "'" for v in items)
        return ",".join(val) if isinstance(val, (list, tuple)) else str(val)

    sql = re.sub(r"\$\{(\w+)(?::(\w+))?\}", lambda m: value(m.group(1), m.group(2) or ""), sql)
    return re.sub(r"\$(?!__)(\w+)", lambda m: value(m.group(1), "") if m.group(1) in variables else m.group(0), sql)


def static_problems(dashboard: Dict) -> List[str]:
    """Rule violations that need no Grafana: duplicate ids, wrong datasource, missing filters."""
    problems = []
    ids = [p["id"] for p in dashboard.get("panels", [])]
    if len(ids) != len(set(ids)):
        problems.append(f"duplicate panel ids: {sorted(ids)}")
    for panel, tgt in iter_targets(dashboard):
        label = f"{panel.get('title')} / {tgt.get('refId')}"
        if tgt.get("datasource", {}).get("uid") != DATASOURCE_UID:
            problems.append(f"{label}: datasource uid is not {DATASOURCE_UID}")
        for fragment in REQUIRED_FRAGMENTS:
            if fragment not in tgt.get("rawSql", ""):
                problems.append(f"{label}: missing {fragment}")
    return problems


def to_ms(value: str, now_ms: int) -> int:
    m = re.fullmatch(r"now(?:-(\d+)d)?", value)
    if m:
        return now_ms - int(m.group(1) or 0) * 86_400_000
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


class Grafana:
    def __init__(self, url: str, user: str, password: str):
        self.url = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    def request(self, method: str, path: str, body: Dict = None) -> Tuple[int, Dict]:
        req = urllib.request.Request(self.url + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")


def run_target(grafana: Grafana, tgt: Dict, sql: str, start_ms: int, end_ms: int) -> Tuple[str, int, float]:
    """Send one query; return (status, rows in the first frame, seconds)."""
    body = {"from": str(start_ms), "to": str(end_ms),
            "queries": [{**tgt, "rawSql": sql, "intervalMs": 3_600_000, "maxDataPoints": 1000}]}
    t0 = time.perf_counter()
    code, resp = grafana.request("POST", "/api/ds/query", body)
    elapsed = time.perf_counter() - t0
    result = resp.get("results", {}).get(tgt["refId"], {})
    if code != 200 or result.get("error"):
        return f"ERROR {code}: {result.get('error') or resp.get('message')}"[:160], 0, elapsed
    frames = result.get("frames", [])
    values = frames[0]["data"]["values"] if frames and frames[0].get("data") else []
    return "ok", len(values[0]) if values else 0, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Static and live checks for the weather Grafana dashboard.")
    parser.add_argument("--dashboard", default=DEFAULT_DASHBOARD)
    parser.add_argument("--grafana-url", default="http://localhost:3000")
    parser.add_argument("--scenarios", default="all", help=f"'all' or comma list of {','.join(s.name for s in SCENARIOS)}")
    parser.add_argument("--static-only", action="store_true")
    args = parser.parse_args()

    with open(args.dashboard, encoding="utf-8") as fh:
        dashboard = json.load(fh)
    n_targets = sum(1 for _ in iter_targets(dashboard))
    problems = static_problems(dashboard)
    print(f"[INFO] {args.dashboard}: {len(dashboard['panels'])} panels/rows, {n_targets} queries")
    for p in problems:
        print(f"[ERROR] {p}", file=sys.stderr)
    if not problems:
        print(f"[INFO] Static rules ok: every query uses '{DATASOURCE_UID}' and filters on "
              + ", ".join(REQUIRED_FRAGMENTS))
    if args.static_only:
        sys.exit(1 if problems else 0)

    load_dotenv()
    grafana = Grafana(args.grafana_url, os.getenv("GRAFANA_ADMIN_USER", "admin"),
                      os.getenv("GRAFANA_ADMIN_PASSWORD", ""))
    code, health = grafana.request("GET", f"/api/datasources/uid/{DATASOURCE_UID}/health")
    print(f"[INFO] Datasource health: HTTP {code} {health.get('status')} - {health.get('message')}")
    failed = code != 200 or health.get("status") != "OK"

    wanted = None if args.scenarios == "all" else set(args.scenarios.split(","))
    now_ms = int(time.time() * 1000)
    rows = []
    for sc in SCENARIOS:
        if wanted and sc.name not in wanted:
            continue
        variables = {"location": sc.location, "time_bin": sc.time_bin, "field": list(ALL_FIELDS)}
        start_ms, end_ms = to_ms(sc.start, now_ms), to_ms(sc.end, now_ms)
        for panel, tgt in iter_targets(dashboard):
            status, n, secs = run_target(grafana, tgt, interpolate(tgt["rawSql"], variables), start_ms, end_ms)
            failed |= status != "ok"
            rows.append({"scenario": sc.name, "panel": panel["title"][:34], "ref": tgt["refId"],
                         "rows": n, "ms": round(secs * 1000), "status": status})
    print_table(rows, 1000)
    if rows:
        per_scenario: Dict[str, List[int]] = {}
        for r in rows:
            per_scenario.setdefault(r["scenario"], []).append(r["ms"])
        print("\n[INFO] Latency per scenario (ms): " + ", ".join(
            f"{k}: max {max(v)} / sum {sum(v)}" for k, v in per_scenario.items()))
    if failed or problems:
        print("[ERROR] Dashboard check failed.", file=sys.stderr)
        sys.exit(1)
    print("[INFO] All panel queries ok.")


if __name__ == "__main__":
    main()

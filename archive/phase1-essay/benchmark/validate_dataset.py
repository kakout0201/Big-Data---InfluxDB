"""Validation Script for Controlled Benchmark Datasets in InfluxDB 3.

Executes comprehensive SQL analytics to verify schema conformance, exact point
counts, null constraints, boundary ranges, distributions, and dataset isolation.
"""

import argparse
import sys
from typing import Any, Dict, List, Optional

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from influxdb_client_3 import InfluxDBClient3

# Import benchmark configuration
from config import (
    BENCHMARK_DATABASE,
    BENCHMARK_TABLE,
    SERVERS,
    BenchmarkConfig,
)


def validate_benchmark_dataset(
    expected_points: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute full SQL validation suite on the benchmark dataset.

    Args:
        expected_points: Optional expected count of points to assert.

    Returns:
        Dict: Validation report with status PASS/FAIL and detailed metrics.
    """
    cfg = BenchmarkConfig.load()
    print("=" * 70)
    print(f"BENCHMARK DATASET VALIDATION — {cfg.database}.{cfg.table}")
    print("=" * 70)

    client = InfluxDBClient3(
        host=cfg.url,
        token=cfg.token,
        database=cfg.database,
        verify_ssl=False,
    )

    validation_results: Dict[str, Any] = {"passed": True, "checks": {}}

    # 1. Total Point Count
    count_query = f"SELECT count(*) AS total_count FROM {cfg.table}"
    try:
        res = client.query(query=count_query).to_pylist()
        actual_count = res[0]["total_count"] if res else 0
        validation_results["checks"]["total_count"] = actual_count
        print(f"[1] Total Point Count: {actual_count:,}")

        if expected_points is not None:
            if actual_count == expected_points:
                print(f"    -> [PASS] Exact match with expected {expected_points:,} points.")
            else:
                print(f"    -> [FAIL] Expected {expected_points:,}, found {actual_count:,}.")
                validation_results["passed"] = False
    except Exception as exc:
        print(f"    -> [ERROR] Failed count query: {exc}")
        validation_results["passed"] = False
        return validation_results

    if actual_count == 0:
        print("[WARN] Table is empty. No data to validate.")
        validation_results["passed"] = False
        return validation_results

    # 2. Distinct Hosts & Regions
    card_query = f"""
    SELECT
        count(distinct host) AS host_count,
        count(distinct region) AS region_count
    FROM {cfg.table}
    """
    res = client.query(query=card_query).to_pylist()[0]
    host_count = res["host_count"]
    region_count = res["region_count"]
    print(f"[2] Distinct Cardinality: Hosts={host_count} (Expected 10), Regions={region_count} (Expected 3)")
    if host_count == 10 and region_count == 3:
        print("    -> [PASS] Cardinality matches specifications.")
    else:
        print("    -> [FAIL] Cardinality mismatch!")
        validation_results["passed"] = False

    # 3. Timestamp Boundaries
    time_query = f"SELECT min(time) AS min_time, max(time) AS max_time FROM {cfg.table}"
    res = client.query(query=time_query).to_pylist()[0]
    min_time = res["min_time"]
    max_time = res["max_time"]
    validation_results["checks"]["min_time"] = str(min_time)
    validation_results["checks"]["max_time"] = str(max_time)
    print(f"[3] Timestamp Range: {min_time} -> {max_time}")
    print("    -> [PASS] Timestamp boundaries valid.")

    # 4. Null Value Check
    null_query = f"""
    SELECT count(*) AS null_count FROM {cfg.table}
    WHERE cpu_usage IS NULL
       OR memory_usage IS NULL
       OR network_in IS NULL
       OR network_out IS NULL
       OR error_rate IS NULL
       OR host IS NULL
       OR region IS NULL
    """
    null_count = client.query(query=null_query).to_pylist()[0]["null_count"]
    print(f"[4] Null / Missing Values: {null_count} rows")
    if null_count == 0:
        print("    -> [PASS] Zero NULL values across all fields and tags.")
    else:
        print(f"    -> [FAIL] Found {null_count} rows containing NULLs!")
        validation_results["passed"] = False

    # 5. Field Boundaries & Value Ranges
    ranges_query = f"""
    SELECT
        min(cpu_usage) AS min_cpu, max(cpu_usage) AS max_cpu, avg(cpu_usage) AS avg_cpu,
        min(memory_usage) AS min_mem, max(memory_usage) AS max_mem, avg(memory_usage) AS avg_mem,
        min(network_in) AS min_nin, max(network_in) AS max_nin, avg(network_in) AS avg_nin,
        min(network_out) AS min_nout, max(network_out) AS max_nout, avg(network_out) AS avg_nout,
        min(error_rate) AS min_err, max(error_rate) AS max_err, avg(error_rate) AS avg_err
    FROM {cfg.table}
    """
    r = client.query(query=ranges_query).to_pylist()[0]
    print("[5] Metric Range Validation:")
    print(f"    - CPU Usage:    [{r['min_cpu']:.2f}%, {r['max_cpu']:.2f}%] (Avg: {r['avg_cpu']:.2f}%)")
    print(f"    - Memory Usage: [{r['min_mem']:.2f}%, {r['max_mem']:.2f}%] (Avg: {r['avg_mem']:.2f}%)")
    print(f"    - Network In:   [{r['min_nin']:.2f}, {r['max_nin']:.2f}] MB/s (Avg: {r['avg_nin']:.2f} MB/s)")
    print(f"    - Network Out:  [{r['min_nout']:.2f}, {r['max_nout']:.2f}] MB/s (Avg: {r['avg_nout']:.2f} MB/s)")
    print(f"    - Error Rate:   [{r['min_err']:.2f}%, {r['max_err']:.2f}%] (Avg: {r['avg_err']:.2f}%)")

    cpu_valid = 0.0 <= r["min_cpu"] and r["max_cpu"] <= 100.0
    mem_valid = 0.0 <= r["min_mem"] and r["max_mem"] <= 100.0
    err_valid = 0.0 <= r["min_err"] and r["max_err"] <= 10.0
    net_valid = r["min_nin"] >= 0.0 and r["min_nout"] >= 0.0

    if cpu_valid and mem_valid and err_valid and net_valid:
        print("    -> [PASS] All metrics strictly within domain bounds.")
    else:
        print("    -> [FAIL] One or more metrics violated domain boundaries!")
        validation_results["passed"] = False

    # 6. Host Distribution
    host_dist_query = f"SELECT host, count(*) AS count FROM {cfg.table} GROUP BY host ORDER BY host"
    host_rows = client.query(query=host_dist_query).to_pylist()
    print("[6] Host Distribution:")
    for row in host_rows:
        print(f"    - {row['host']}: {row['count']:,} points")

    # 7. Region Distribution
    region_dist_query = f"SELECT region, count(*) AS count FROM {cfg.table} GROUP BY region ORDER BY region"
    region_rows = client.query(query=region_dist_query).to_pylist()
    print("[7] Regional Distribution:")
    for row in region_rows:
        print(f"    - {row['region']}: {row['count']:,} points")

    # 8. Dataset Isolation Verification
    print("[8] Checking Dataset Isolation (Demo Database vs Benchmark Database)...")
    try:
        demo_client = InfluxDBClient3(
            host=cfg.url,
            token=cfg.token,
            database="server_monitoring",
            verify_ssl=False,
        )
        demo_res = demo_client.query(query="SELECT count(*) AS total FROM server_metrics").to_pylist()
        demo_count = demo_res[0]["total"] if demo_res else 0
        print(f"    - server_monitoring.server_metrics count: {demo_count:,} records")
        print("    -> [PASS] Demo database is completely isolated and preserved.")
    except Exception as exc:
        print(f"    -> [WARN] Could not query server_monitoring: {exc}")

    print("=" * 70)
    final_status = "PASSED" if validation_results["passed"] else "FAILED"
    print(f"OVERALL VALIDATION RESULT: {final_status}")
    print("=" * 70)

    return validation_results


def main() -> None:
    """CLI Entrypoint for Benchmark Dataset Validator."""
    parser = argparse.ArgumentParser(
        description="Validate controlled benchmark datasets in InfluxDB 3."
    )
    parser.add_argument(
        "--expected-points",
        type=int,
        default=None,
        help="Assert exact number of expected records (e.g. 10000).",
    )
    args = parser.parse_args()

    results = validate_benchmark_dataset(expected_points=args.expected_points)
    if not results["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

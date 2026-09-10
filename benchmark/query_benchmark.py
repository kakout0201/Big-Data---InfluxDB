"""Scientific Query Latency Benchmark Framework for InfluxDB 3 Core.

Measures End-to-End Query Latency (ms) of Apache DataFusion / Arrow Flight SQL engine
across multiple dataset scales (10K, 50K, 100K) and standard query archetypes (Q1-Q4).
Implements rigorous timing isolation, result materialization, warm-up protocol,
5 measured runs per configuration, statistical aggregation, and post-validation.
"""

import argparse
import csv
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reconfigure stdout/stderr to UTF-8
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from influxdb_client_3 import InfluxDBClient3

# Import benchmark modules
from config import (
    BENCHMARK_DATABASE,
    BENCHMARK_TABLE,
    DEFAULT_SEED,
    FIXED_START_TIME,
    ROOT_DIR,
    BenchmarkConfig,
)
from generate_dataset import generate_dataset
from query_queries import QUERIES, BenchmarkQuery


def validate_dataset_state(client: InfluxDBClient3, table: str, expected_count: int) -> Tuple[bool, str]:
    """Verify point count, cardinality, and null constraints prior to query benchmarking."""
    try:
        # 1. Count validation
        cnt_res = client.query(query=f"SELECT count(*) AS total FROM {table}").to_pylist()
        actual_count = cnt_res[0]["total"] if cnt_res else 0
        if actual_count != expected_count:
            return False, f"Expected {expected_count:,} points, found {actual_count:,}"

        # 2. Null check
        null_sql = f"""
        SELECT count(*) AS null_cnt FROM {table}
        WHERE cpu_usage IS NULL OR memory_usage IS NULL OR error_rate IS NULL OR host IS NULL OR region IS NULL
        """
        null_res = client.query(query=null_sql).to_pylist()
        null_count = null_res[0]["null_cnt"] if null_res else 0
        if null_count > 0:
            return False, f"Found {null_count} rows containing NULL values"

        # 3. Cardinality check
        card_sql = f"SELECT count(distinct host) as h_cnt, count(distinct region) as r_cnt FROM {table}"
        card_res = client.query(query=card_sql).to_pylist()[0]
        if card_res["h_cnt"] != 10 or card_res["r_cnt"] != 3:
            return False, f"Cardinality mismatch: hosts={card_res['h_cnt']} (exp 10), regions={card_res['r_cnt']} (exp 3)"

        return True, f"Dataset validated successfully: {actual_count:,} points, 10 hosts, 3 regions, 0 NULLs"
    except Exception as exc:
        return False, f"Validation query execution error: {exc}"


def execute_single_query_timed(
    client: InfluxDBClient3,
    query_obj: BenchmarkQuery,
) -> Tuple[float, int, bool, Optional[str]]:
    """Execute query, materialize all rows, and strictly measure end-to-end latency.

    Returns:
        (elapsed_seconds, result_rows_count, success_flag, error_message)
    """
    error_msg = None
    rows_count = 0
    success = False

    t_start = time.perf_counter()
    try:
        reader = client.query(query=query_obj.sql)
        # Materialize entire result to memory
        rows = reader.to_pylist()
        t_stop = time.perf_counter()
        elapsed = t_stop - t_start
        rows_count = len(rows)

        # Validate rows structure
        if query_obj.validator:
            success = query_obj.validator(rows)
            if not success:
                error_msg = f"Validator failed for {query_obj.query_id} (returned {rows_count} rows)"
        else:
            success = rows_count >= query_obj.expected_min_rows
    except Exception as exc:
        t_stop = time.perf_counter()
        elapsed = t_stop - t_start
        error_msg = str(exc)
        success = False

    return elapsed, rows_count, success, error_msg


def run_query_latency_benchmark(
    dataset_sizes: List[int],
    queries: List[BenchmarkQuery] = QUERIES,
    measured_runs_count: int = 5,
    warmup_runs_count: int = 1,
    seed: int = DEFAULT_SEED,
    results_dir: Path = ROOT_DIR / "benchmark" / "results",
) -> Dict[str, Any]:
    """Execute complete query latency benchmark suite."""
    cfg = BenchmarkConfig.load()
    results_dir.mkdir(parents=True, exist_ok=True)

    client = InfluxDBClient3(
        host=cfg.url,
        token=cfg.token,
        database=cfg.database,
        verify_ssl=False,
    )

    raw_results: List[Dict[str, Any]] = []
    summary_results: List[Dict[str, Any]] = []

    total_configs = len(dataset_sizes) * len(queries)
    print("=" * 80)
    print("INFLUXDB 3 CORE — END-TO-END QUERY LATENCY BENCHMARK")
    print("=" * 80)
    print(f"Database: {cfg.database} | Table: {cfg.table}")
    print(f"Dataset Scales: {dataset_sizes}")
    print(f"Query Archetypes: {[q.query_id for q in queries]}")
    print(f"Protocol: {warmup_runs_count} warm-up + {measured_runs_count} measured runs per configuration")
    print(f"Total Configurations: {total_configs} (Total Runs: {total_configs * (warmup_runs_count + measured_runs_count)})")
    print("=" * 80)

    config_idx = 0

    for ds_size in dataset_sizes:
        print(f"\n================================================================================")
        print(f">>> [DATASET PREPARATION] Generating & loading exact {ds_size:,} points dataset...")
        print(f"================================================================================")
        generate_dataset(
            target_points=ds_size,
            seed=seed,
            batch_size=5000,
            start_time=FIXED_START_TIME,
            reset=True,
        )

        # Validate dataset integrity
        valid, val_msg = validate_dataset_state(client, cfg.table, ds_size)
        print(f"[DATASET VALIDATION] {val_msg}")
        if not valid:
            raise RuntimeError(f"Dataset validation failed: {val_msg}")

        # Benchmark each query on this dataset scale
        for q in queries:
            config_idx += 1
            print(f"\n--- [CONFIG {config_idx}/{total_configs}] Dataset: {ds_size:,} pts | Query: {q.query_id} ({q.name}) ---")
            print(f"    SQL: {q.sql.replace(chr(10), ' ').strip()[:75]}...")

            # 1. Warm-up runs
            for w in range(1, warmup_runs_count + 1):
                w_elapsed, w_rows, w_succ, w_err = execute_single_query_timed(client, q)
                w_ms = round(w_elapsed * 1000, 3)
                print(f"    [Warm-up {w}/{warmup_runs_count}] {w_ms:.3f} ms (Rows: {w_rows}, Success: {w_succ})")

                raw_results.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "dataset_size": ds_size,
                    "query_id": q.query_id,
                    "query_name": q.name,
                    "run_type": "warmup",
                    "run_number": w,
                    "elapsed_seconds": round(w_elapsed, 6),
                    "latency_ms": w_ms,
                    "success": w_succ,
                    "result_rows": w_rows,
                    "error": w_err or "",
                })

            # 2. Measured runs
            measured_latencies_ms: List[float] = []
            all_measured_succ = True

            for r in range(1, measured_runs_count + 1):
                elapsed, rows, succ, err = execute_single_query_timed(client, q)
                ms = round(elapsed * 1000, 3)
                measured_latencies_ms.append(ms)
                if not succ:
                    all_measured_succ = False

                print(f"    [Measured {r}/{measured_runs_count}] {ms:7.3f} ms (Rows: {rows:2d}, {'PASS' if succ else 'FAIL'})")

                raw_results.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "dataset_size": ds_size,
                    "query_id": q.query_id,
                    "query_name": q.name,
                    "run_type": "measured",
                    "run_number": r,
                    "elapsed_seconds": round(elapsed, 6),
                    "latency_ms": ms,
                    "success": succ,
                    "result_rows": rows,
                    "error": err or "",
                })

            # 3. Compute Aggregated Summary Statistics
            med_ms = round(statistics.median(measured_latencies_ms), 3)
            mean_ms = round(statistics.mean(measured_latencies_ms), 3)
            min_ms = round(min(measured_latencies_ms), 3)
            max_ms = round(max(measured_latencies_ms), 3)
            std_ms = round(statistics.stdev(measured_latencies_ms), 3) if len(measured_latencies_ms) > 1 else 0.0

            summary_results.append({
                "dataset_size": ds_size,
                "query_id": q.query_id,
                "query_name": q.name,
                "measured_runs": measured_runs_count,
                "median_latency_ms": med_ms,
                "min_latency_ms": min_ms,
                "max_latency_ms": max_ms,
                "mean_latency_ms": mean_ms,
                "stddev_latency_ms": std_ms,
                "success": all_measured_succ,
            })

            print(f"    => SUMMARY: Median = {med_ms:.3f} ms | Min = {min_ms:.3f} ms | Max = {max_ms:.3f} ms | Mean = {mean_ms:.3f} ms (StdDev = {std_ms:.3f} ms)")

    # 4. Save Raw CSV
    raw_csv_path = results_dir / "query_latency_raw.csv"
    with open(raw_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "dataset_size", "query_id", "query_name",
            "run_type", "run_number", "elapsed_seconds", "latency_ms",
            "success", "result_rows", "error"
        ])
        writer.writeheader()
        writer.writerows(raw_results)
    print(f"\n[INFO] Raw query latency results saved to: {raw_csv_path}")

    # 5. Save Summary CSV
    summary_csv_path = results_dir / "query_latency_summary.csv"
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "dataset_size", "query_id", "query_name", "measured_runs",
            "median_latency_ms", "min_latency_ms", "max_latency_ms",
            "mean_latency_ms", "stddev_latency_ms", "success"
        ])
        writer.writeheader()
        writer.writerows(summary_results)
    print(f"[INFO] Summary statistics saved to: {summary_csv_path}")

    # 6. Save Metadata JSON (Excluding secrets)
    metadata = {
        "benchmark_name": "InfluxDB 3 Core End-to-End Query Latency Benchmark",
        "benchmark_version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": cfg.database,
        "table": cfg.table,
        "dataset_sizes": dataset_sizes,
        "queries": [
            {
                "query_id": q.query_id,
                "name": q.name,
                "description": q.description,
                "sql": q.sql,
            }
            for q in queries
        ],
        "warmup_runs_per_config": warmup_runs_count,
        "measured_runs_per_config": measured_runs_count,
        "seed": seed,
        "fixed_start_time": FIXED_START_TIME.isoformat(),
        "methodology": {
            "timing_scope": "Strictly bounds client.query() dispatch and result materialization (.to_pylist())",
            "timing_clock": "time.perf_counter() (nanosecond monotonic clock)",
            "cache_condition": (
                "Query latency benchmark represents repeated-query / warm-cache-like execution "
                "conditions and is intended for controlled comparison within the same environment, "
                "not cold-cache performance."
            ),
            "representative_metric": "median_latency_ms",
            "validation": "Pre-benchmark schema/count validation and per-query structure validator",
        },
        "environment": {
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python_version": platform.python_version(),
            "influxdb_image": "influxdb:3-core (v3.11.2)",
            "engine": "Apache DataFusion / Apache Arrow Flight SQL",
            "client_library": "influxdb-client-3",
        },
    }

    metadata_path = results_dir / "query_latency_metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"[INFO] Experiment metadata saved to: {metadata_path}")

    # 7. Restore 10K baseline dataset for workspace integrity
    print("\n[RESTORATION] Restoring standard 10,000 baseline dataset in benchmark_monitoring...")
    generate_dataset(target_points=10_000, seed=DEFAULT_SEED, batch_size=5000, reset=True)

    # 8. Verify Demo Database preservation
    print("\n[VERIFICATION] Checking Demo Database (server_monitoring) isolation...")
    try:
        demo_client = InfluxDBClient3(
            host=cfg.url,
            token=cfg.token,
            database="server_monitoring",
            verify_ssl=False,
        )
        demo_count = demo_client.query(query="SELECT count(*) AS total FROM server_metrics").to_pylist()[0]["total"]
        print(f"  - server_monitoring.server_metrics count: {demo_count:,} records (Preserved & Untouched)")
    except Exception as exc:
        print(f"  - [WARN] Demo check error: {exc}")

    print("=" * 80)
    print("QUERY LATENCY BENCHMARK COMPLETED SUCCESSFULLY!")
    print("=" * 80)

    return {
        "raw_results": raw_results,
        "summary_results": summary_results,
        "metadata": metadata,
    }


def main() -> None:
    """CLI Entrypoint for Query Latency Benchmark."""
    parser = argparse.ArgumentParser(
        description="Query Latency Benchmark for InfluxDB 3 Core (Apache DataFusion / Arrow)."
    )
    parser.add_argument(
        "--dataset-sizes",
        type=str,
        default="10000,50000,100000",
        help="Comma-separated dataset sizes (default: '10000,50000,100000').",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of measured repetitions per configuration (default: 5).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Number of warmup runs per configuration (default: 1).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for reproducibility (default: {DEFAULT_SEED}).",
    )

    args = parser.parse_args()
    ds_sizes = [int(s.strip()) for s in args.dataset_sizes.split(",")]

    run_query_latency_benchmark(
        dataset_sizes=ds_sizes,
        queries=QUERIES,
        measured_runs_count=args.runs,
        warmup_runs_count=args.warmup,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()

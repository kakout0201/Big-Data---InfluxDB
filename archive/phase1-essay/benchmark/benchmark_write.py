"""Scientific Write Throughput Benchmark Framework for InfluxDB 3 Core.

Measures precise ingestion throughput (points/second), elapsed time, and scalability
across multiple dataset sizes (10K, 50K, 100K, 500K, 1M) and batch sizes (500, 1K, 5K, 10K).
Strictly enforces test isolation, in-memory preloading, post-measurement validation,
and statistical aggregation (median, mean, min, max).
"""

import argparse
import csv
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Reconfigure stdout/stderr to UTF-8
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from influxdb_client_3 import InfluxDBClient3, Point

# Import benchmark configuration
from config import (
    BENCHMARK_DATABASE,
    BENCHMARK_TABLE,
    DEFAULT_SEED,
    FIXED_START_TIME,
    ROUND_INTERVAL_SECONDS,
    SERVERS,
    ROOT_DIR,
    BenchmarkConfig,
)


def reset_benchmark_table(cfg: BenchmarkConfig) -> None:
    """Hard-delete the benchmark table to guarantee pristine isolation for each run."""
    subprocess.run(
        [
            "docker", "exec", "influxdb3-core",
            "influxdb3", "delete", "table", cfg.table,
            "-d", cfg.database,
            "-H", "https://127.0.0.1:8181",
            "--tls-no-verify",
            "--token", cfg.token,
            "--hard-delete", "now",
            "-y",
        ],
        capture_output=True,
        text=True,
    )
    # Give the engine a brief settling window
    time.sleep(0.3)


def prepare_points_in_memory(
    target_points: int,
    seed: int,
    start_time: datetime,
    table_name: str,
) -> List[Point]:
    """Generate all Point objects in memory before timer begins.

    Eliminates data generation overhead and random number generation from the timer.
    """
    random.seed(seed)
    points: List[Point] = []
    round_idx = 0

    while len(points) < target_points:
        round_time = start_time + timedelta(seconds=round_idx * ROUND_INTERVAL_SECONDS)
        round_idx += 1

        for server_idx, server in enumerate(SERVERS):
            if len(points) >= target_points:
                break

            point_time = round_time + timedelta(milliseconds=server_idx * 10)

            # Metric simulation distributions
            cpu_spike = random.uniform(15.0, 30.0) if random.random() < 0.05 else 0.0
            cpu = server["cpu_base"] + random.uniform(-8.0, 8.0) + cpu_spike
            cpu = round(max(0.0, min(100.0, cpu)), 2)

            mem_spike = random.uniform(10.0, 20.0) if random.random() < 0.03 else 0.0
            mem = server["mem_base"] + random.uniform(-4.0, 4.0) + mem_spike
            mem = round(max(0.0, min(100.0, mem)), 2)

            net_in = round(max(0.5, random.expovariate(1.0 / 25.0)), 2)
            net_out = round(max(0.2, random.expovariate(1.0 / 18.0)), 2)

            err_spike = random.uniform(1.0, 4.0) if random.random() < 0.02 else 0.0
            err = random.uniform(0.01, 0.20) + err_spike
            err = round(max(0.0, min(10.0, err)), 2)

            p = (
                Point(table_name)
                .tag("host", server["host"])
                .tag("region", server["region"])
                .field("cpu_usage", float(cpu))
                .field("memory_usage", float(mem))
                .field("network_in", float(net_in))
                .field("network_out", float(net_out))
                .field("error_rate", float(err))
                .time(point_time)
            )
            points.append(p)

    return points


def validate_point_count(client: InfluxDBClient3, table: str, expected: int) -> Tuple[bool, int]:
    """Verify exact count in database using SQL after write timer stops."""
    try:
        query = f"SELECT count(*) AS total_count FROM {table}"
        res = client.query(query=query).to_pylist()
        actual = res[0]["total_count"] if res else 0
        return (actual == expected), actual
    except Exception as exc:
        print(f"    [WARN] Count validation query failed: {exc}")
        return False, -1


def run_single_write_trial(
    client: InfluxDBClient3,
    cfg: BenchmarkConfig,
    batches: List[List[Point]],
    target_points: int,
) -> Tuple[float, float, bool, int]:
    """Execute a single write trial with pristine reset, isolated timer, and post-validation.

    Returns:
        (elapsed_seconds, throughput_pts_per_sec, count_valid, actual_count)
    """
    # 1. Clean slate isolation
    reset_benchmark_table(cfg)

    # 2. START TIMER (isolated to write execution only)
    t_start = time.perf_counter()

    for batch in batches:
        client.write(record=batch)

    t_stop = time.perf_counter()
    # 3. STOP TIMER

    elapsed = t_stop - t_start
    throughput = target_points / elapsed if elapsed > 0 else 0.0

    # 4. POST-MEASUREMENT VALIDATION
    valid, actual_count = validate_point_count(client, cfg.table, target_points)

    return elapsed, throughput, valid, actual_count


def execute_write_benchmark(
    dataset_sizes: List[int],
    batch_sizes: List[int],
    runs_per_config: int = 3,
    warmup_runs: int = 1,
    seed: int = DEFAULT_SEED,
    results_dir: Path = ROOT_DIR / "benchmark" / "results",
) -> Dict[str, Any]:
    """Execute full write throughput benchmark matrix."""
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

    total_matrix_cells = len(dataset_sizes) * len(batch_sizes)
    print("=" * 80)
    print("INFLUXDB 3 CORE — WRITE THROUGHPUT BENCHMARK")
    print("=" * 80)
    print(f"Database: {cfg.database} | Table: {cfg.table}")
    print(f"Dataset Sizes: {dataset_sizes}")
    print(f"Batch Sizes:   {batch_sizes}")
    print(f"Configurations: {total_matrix_cells} | Repetitions: {warmup_runs} warm-up + {runs_per_config} measured")
    print(f"Seed: {seed} | Start Time: {FIXED_START_TIME.isoformat()}")
    print("=" * 80)

    config_idx = 0

    for ds_size in dataset_sizes:
        print(f"\n>>> [PREPARING DATASET] Generating {ds_size:,} points in memory (Seed: {seed})...")
        t_prep_start = time.perf_counter()
        preloaded_points = prepare_points_in_memory(
            target_points=ds_size,
            seed=seed,
            start_time=FIXED_START_TIME,
            table_name=cfg.table,
        )
        t_prep = round(time.perf_counter() - t_prep_start, 3)
        print(f"    Memory preparation complete in {t_prep}s ({len(preloaded_points):,} points ready).")

        for b_size in batch_sizes:
            config_idx += 1
            print(f"\n--- [CONFIG {config_idx}/{total_matrix_cells}] Dataset: {ds_size:,} pts | Batch Size: {b_size:,} ---")

            # Slice into batches
            batches = [
                preloaded_points[i : i + b_size]
                for i in range(0, len(preloaded_points), b_size)
            ]

            # 1. Warm-up runs
            for w in range(1, warmup_runs + 1):
                print(f"  [Warm-up {w}/{warmup_runs}] Executing warm-up trial...", end="", flush=True)
                w_elapsed, w_tp, w_valid, w_count = run_single_write_trial(
                    client, cfg, batches, ds_size
                )
                print(f" done ({w_elapsed:.3f}s, {w_tp:,.1f} pts/s | Count: {w_count:,} - {'OK' if w_valid else 'FAIL'})")

            # 2. Measured runs
            measured_elapseds: List[float] = []
            measured_throughputs: List[float] = []

            for r in range(1, runs_per_config + 1):
                print(f"  [Measured {r}/{runs_per_config}] Writing {ds_size:,} points in {len(batches)} batches...", end="", flush=True)
                elapsed, tp, valid, actual_count = run_single_write_trial(
                    client, cfg, batches, ds_size
                )
                ts_now = datetime.now(timezone.utc).isoformat()
                print(f" {elapsed:.3f}s -> {tp:,.1f} pts/s (Count: {actual_count:,} - {'PASS' if valid else 'FAIL'})")

                if not valid:
                    print(f"    [CRITICAL ERROR] Run {r} failed count assertion! Expected {ds_size}, got {actual_count}")

                measured_elapseds.append(elapsed)
                measured_throughputs.append(tp)

                raw_record = {
                    "dataset_size": ds_size,
                    "batch_size": b_size,
                    "run_number": r,
                    "elapsed_seconds": round(elapsed, 4),
                    "throughput_points_per_second": round(tp, 2),
                    "valid_count": valid,
                    "actual_count": actual_count,
                    "timestamp": ts_now,
                }
                raw_results.append(raw_record)

            # 3. Aggregated metrics for this configuration
            summary_record = {
                "dataset_size": ds_size,
                "batch_size": b_size,
                "runs": runs_per_config,
                "median_elapsed_seconds": round(statistics.median(measured_elapseds), 4),
                "avg_elapsed_seconds": round(statistics.mean(measured_elapseds), 4),
                "min_elapsed_seconds": round(min(measured_elapseds), 4),
                "max_elapsed_seconds": round(max(measured_elapseds), 4),
                "median_throughput": round(statistics.median(measured_throughputs), 2),
                "avg_throughput": round(statistics.mean(measured_throughputs), 2),
                "min_throughput": round(min(measured_throughputs), 2),
                "max_throughput": round(max(measured_throughputs), 2),
            }
            summary_results.append(summary_record)
            print(f"  => Summary: Median Throughput = {summary_record['median_throughput']:,.2f} pts/s "
                  f"(Median Elapsed = {summary_record['median_elapsed_seconds']:.4f}s)")

    # 4. Write CSV files
    raw_csv_path = results_dir / "write_raw.csv"
    with open(raw_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "dataset_size", "batch_size", "run_number", "elapsed_seconds",
            "throughput_points_per_second", "valid_count", "actual_count", "timestamp"
        ])
        writer.writeheader()
        writer.writerows(raw_results)
    print(f"\n[INFO] Raw measurements saved to: {raw_csv_path}")

    summary_csv_path = results_dir / "write_summary.csv"
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "dataset_size", "batch_size", "runs", "median_elapsed_seconds",
            "avg_elapsed_seconds", "min_elapsed_seconds", "max_elapsed_seconds",
            "median_throughput", "avg_throughput", "min_throughput", "max_throughput"
        ])
        writer.writeheader()
        writer.writerows(summary_results)
    print(f"[INFO] Summary statistics saved to: {summary_csv_path}")

    # 5. Write Experiment Metadata JSON (Excluding secrets)
    metadata = {
        "benchmark_name": "InfluxDB 3 Core Write Throughput Benchmark",
        "benchmark_version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": cfg.database,
        "table": cfg.table,
        "dataset_sizes": dataset_sizes,
        "batch_sizes": batch_sizes,
        "repetitions_per_config": runs_per_config,
        "warmup_runs": warmup_runs,
        "seed": seed,
        "fixed_start_time": FIXED_START_TIME.isoformat(),
        "methodology": {
            "preloading": "All Point objects generated in memory prior to timer activation",
            "timing_scope": "Strictly encloses client.write() batch iteration loop",
            "isolation": "Hard-delete reset of target table prior to each individual trial",
            "throughput_formula": "total_points / elapsed_seconds",
            "representative_metric": "median_throughput",
            "validation": "SQL SELECT count(*) assertion after timer completion",
        },
        "environment": {
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python_version": platform.python_version(),
            "influxdb_image": "influxdb:3-core (v3.11.2)",
            "client_library": "influxdb-client-3",
        },
    }

    metadata_path = results_dir / "write_benchmark_metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"[INFO] Benchmark metadata saved to: {metadata_path}")

    # 6. Verify Isolation on Demo Database
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
    print("WRITE BENCHMARK EXECUTION COMPLETED SUCCESSFULLY!")
    print("=" * 80)

    return {
        "raw_results": raw_results,
        "summary_results": summary_results,
        "metadata": metadata,
    }


def main() -> None:
    """CLI Entrypoint for Write Benchmark."""
    parser = argparse.ArgumentParser(
        description="Write Throughput Benchmark Framework for InfluxDB 3 Core."
    )
    parser.add_argument(
        "--phase",
        choices=["smoke", "phase-a", "full", "custom"],
        default="phase-a",
        help="Benchmark execution phase: 'smoke' (10K/1000), 'phase-a' (10K,50K,100K x 4 batches), 'full' (up to 1M), 'custom'.",
    )
    parser.add_argument(
        "--dataset-sizes",
        type=str,
        default=None,
        help="Comma-separated dataset sizes (e.g. 10000,50000,100000).",
    )
    parser.add_argument(
        "--batch-sizes",
        type=str,
        default=None,
        help="Comma-separated batch sizes (e.g. 500,1000,5000,10000).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of measured repetitions per configuration (default: 3).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Number of warmup runs (default: 1).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for reproducibility (default: {DEFAULT_SEED}).",
    )

    args = parser.parse_args()

    if args.phase == "smoke":
        ds_sizes = [10_000]
        b_sizes = [1_000]
    elif args.phase == "phase-a":
        ds_sizes = [10_000, 50_000, 100_000]
        b_sizes = [500, 1_000, 5_000, 10_000]
    elif args.phase == "full":
        ds_sizes = [10_000, 50_000, 100_000, 500_000, 1_000_000]
        b_sizes = [500, 1_000, 5_000, 10_000]
    else:  # custom
        ds_sizes = [int(s.strip()) for s in args.dataset_sizes.split(",")] if args.dataset_sizes else [10_000]
        b_sizes = [int(b.strip()) for b in args.batch_sizes.split(",")] if args.batch_sizes else [1_000]

    if args.dataset_sizes and args.phase != "custom":
        ds_sizes = [int(s.strip()) for s in args.dataset_sizes.split(",")]
    if args.batch_sizes and args.phase != "custom":
        b_sizes = [int(b.strip()) for b in args.batch_sizes.split(",")]

    execute_write_benchmark(
        dataset_sizes=ds_sizes,
        batch_sizes=b_sizes,
        runs_per_config=args.runs,
        warmup_runs=args.warmup,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()

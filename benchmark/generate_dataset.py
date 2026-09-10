"""Reproducible Benchmark Dataset Generator for InfluxDB 3.

Generates controlled, deterministic time-series datasets of exact sizes
(10K, 50K, 100K, 500K, 1M) for performance and experimental evaluation.
"""

import argparse
import json
import random
import subprocess
import sys

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

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
    DEFAULT_BATCH_SIZE,
    DEFAULT_SEED,
    FIXED_START_TIME,
    ROUND_INTERVAL_SECONDS,
    SERVERS,
    ROOT_DIR,
    BenchmarkConfig,
)


def reset_benchmark_table() -> None:
    """Drop the benchmark table in benchmark_monitoring database."""
    cfg = BenchmarkConfig.load()
    print(f"[INFO] Resetting table '{cfg.table}' in database '{cfg.database}'...")
    res = subprocess.run(
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
    if res.returncode == 0:
        print(f"[INFO] Table '{cfg.table}' reset successfully.")
    else:
        print(f"[WARN] Table reset response: {res.stderr.strip() or res.stdout.strip()}")


def generate_metric_point(
    server: Dict[str, Any],
    timestamp: datetime,
    table_name: str = BENCHMARK_TABLE,
) -> Point:
    """Generate a single deterministic Point with realistic noise and bounded distributions.

    Args:
        server: Dictionary containing host, region, and baseline values.
        timestamp: The UTC timestamp for this point.
        table_name: Target measurement name.

    Returns:
        Point: Formatted InfluxDB Point.
    """
    # CPU usage: baseline + normal fluctuation [-8.0, +8.0] + occasional spike (+15-30 with 5% chance)
    cpu_spike = random.uniform(15.0, 30.0) if random.random() < 0.05 else 0.0
    cpu = server["cpu_base"] + random.uniform(-8.0, 8.0) + cpu_spike
    cpu = round(max(0.0, min(100.0, cpu)), 2)

    # Memory usage: baseline + variation [-4.0, +4.0] + load fluctuation
    mem_spike = random.uniform(10.0, 20.0) if random.random() < 0.03 else 0.0
    mem = server["mem_base"] + random.uniform(-4.0, 4.0) + mem_spike
    mem = round(max(0.0, min(100.0, mem)), 2)

    # Network I/O (MB/s): baseline + exponential variation
    net_in = round(max(0.5, random.expovariate(1.0 / 25.0)), 2)
    net_out = round(max(0.2, random.expovariate(1.0 / 18.0)), 2)

    # Error rate (%): nominal 0.01 - 0.20% with rare spike
    err_spike = random.uniform(1.0, 4.0) if random.random() < 0.02 else 0.0
    err = random.uniform(0.01, 0.20) + err_spike
    err = round(max(0.0, min(10.0, err)), 2)

    point = (
        Point(table_name)
        .tag("host", server["host"])
        .tag("region", server["region"])
        .field("cpu_usage", float(cpu))
        .field("memory_usage", float(mem))
        .field("network_in", float(net_in))
        .field("network_out", float(net_out))
        .field("error_rate", float(err))
        .time(timestamp)
    )
    return point


def generate_dataset(
    target_points: int,
    seed: int = DEFAULT_SEED,
    batch_size: int = DEFAULT_BATCH_SIZE,
    start_time: datetime = FIXED_START_TIME,
    reset: bool = False,
) -> Dict[str, Any]:
    """Generate and ingest an exact number of benchmark points into InfluxDB 3.

    Args:
        target_points: Total number of points to generate.
        seed: Random seed for 100% reproducibility.
        batch_size: Number of points written per API batch.
        start_time: Base UTC timestamp for the time-series.
        reset: If True, resets the target table before writing.

    Returns:
        Dict: Metadata summary of the generated dataset.
    """
    if target_points <= 0:
        raise ValueError(f"target_points must be > 0, got {target_points}")
    if batch_size <= 0:
        raise ValueError(f"batch_size must be > 0, got {batch_size}")

    if reset:
        reset_benchmark_table()

    # Set random seed
    random.seed(seed)
    print(f"[INFO] Initialized random seed: {seed}")

    # Load configuration
    cfg = BenchmarkConfig.load()
    print(f"[INFO] Target: Database='{cfg.database}', Table='{cfg.table}'")
    print(f"[INFO] Target Points: {target_points:,} | Batch Size: {batch_size:,}")
    print(f"[INFO] Start Time: {start_time.isoformat()}")

    # Initialize client
    client = InfluxDBClient3(
        host=cfg.url,
        token=cfg.token,
        database=cfg.database,
        verify_ssl=False,
    )

    total_generated = 0
    total_batches = 0
    current_batch: List[Point] = []
    round_idx = 0
    num_servers = len(SERVERS)

    first_point_time = None
    last_point_time = None

    t_start = time.perf_counter()

    while total_generated < target_points:
        round_time = start_time + timedelta(seconds=round_idx * ROUND_INTERVAL_SECONDS)
        round_idx += 1

        for server_idx, server in enumerate(SERVERS):
            if total_generated >= target_points:
                break

            # Stagger point timestamp slightly within the round to maintain strict chronological order
            point_time = round_time + timedelta(milliseconds=server_idx * 10)
            if first_point_time is None:
                first_point_time = point_time
            last_point_time = point_time

            point = generate_metric_point(server, point_time, cfg.table)
            current_batch.append(point)
            total_generated += 1

            # Flush batch when capacity reached
            if len(current_batch) >= batch_size:
                client.write(record=current_batch)
                total_batches += 1
                current_batch = []
                if total_batches % 5 == 0 or total_generated == target_points:
                    print(
                        f"[PROGRESS] Written {total_generated:,}/{target_points:,} points "
                        f"({total_batches} batches)"
                    )

    # Flush any remaining points
    if current_batch:
        client.write(record=current_batch)
        total_batches += 1
        print(f"[PROGRESS] Written {total_generated:,}/{target_points:,} points ({total_batches} batches)")

    duration = round(time.perf_counter() - t_start, 3)
    print(f"[SUCCESS] Dataset generation complete in {duration}s. Total points written: {total_generated:,}")

    # Build metadata record (excluding secrets)
    metadata = {
        "dataset_name": f"server_metrics_benchmark_{total_generated}",
        "dataset_size": total_generated,
        "seed": seed,
        "database": cfg.database,
        "table": cfg.table,
        "number_of_servers": num_servers,
        "number_of_regions": 3,
        "servers": [s["host"] for s in SERVERS],
        "regions": sorted(list(set(s["region"] for s in SERVERS))),
        "tags": ["host", "region"],
        "fields": ["cpu_usage", "memory_usage", "network_in", "network_out", "error_rate"],
        "start_time": first_point_time.isoformat() if first_point_time else None,
        "end_time": last_point_time.isoformat() if last_point_time else None,
        "round_interval_seconds": ROUND_INTERVAL_SECONDS,
        "batch_size": batch_size,
        "total_batches": total_batches,
        "generation_duration_seconds": duration,
        "generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "generator_version": "1.0.0",
    }

    # Save metadata to benchmark/results/
    results_dir = ROOT_DIR / "benchmark" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = results_dir / f"dataset_{total_generated}.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"[INFO] Dataset metadata saved to: {metadata_file}")

    return metadata


def main() -> None:
    """CLI Entrypoint for Benchmark Data Generator."""
    parser = argparse.ArgumentParser(
        description="Controlled Benchmark Dataset Generator for InfluxDB 3 Core."
    )
    parser.add_argument(
        "--points",
        type=int,
        required=True,
        help="Exact number of points to generate (e.g. 10000, 50000, 100000, 500000, 1000000).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for reproducibility (default: {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Number of points per write batch (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--start-time",
        type=str,
        default=None,
        help="Base start time in ISO 8601 format (default: 2026-01-01T00:00:00Z).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate benchmark table before generating points.",
    )

    args = parser.parse_args()

    start_dt = FIXED_START_TIME
    if args.start_time:
        try:
            start_dt = datetime.fromisoformat(args.start_time)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except Exception as exc:
            print(f"[ERROR] Invalid start-time '{args.start_time}': {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        generate_dataset(
            target_points=args.points,
            seed=args.seed,
            batch_size=args.batch_size,
            start_time=start_dt,
            reset=args.reset,
        )
    except Exception as exc:
        print(f"[ERROR] Failed to generate benchmark dataset: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Time-Series Data Generator for InfluxDB 3 Core.

Simulates infrastructure telemetry for 10 servers across 3 geographic regions:
- Region 'hcm':    server-01, server-02, server-03, server-04
- Region 'hanoi':  server-05, server-06, server-07
- Region 'danang': server-08, server-09, server-10

Metrics generated per server:
- cpu_usage:    0.0% - 100.0%
- memory_usage: 0.0% - 100.0%
- network_in:   positive float (MB/s)
- network_out:  positive float (MB/s)
- error_rate:   0.0% - 10.0%
- timestamp:    UTC datetime (nanosecond precision)
"""

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

from influxdb_client_3 import InfluxDBClient3, Point

# Import configuration helper
from config import InfluxDBConfig


# Fixed server distribution across 3 regions
SERVERS: List[Dict[str, Any]] = [
    {"host": "server-01", "region": "hcm", "cpu_base": 35.0, "mem_base": 55.0},
    {"host": "server-02", "region": "hcm", "cpu_base": 42.0, "mem_base": 60.0},
    {"host": "server-03", "region": "hcm", "cpu_base": 50.0, "mem_base": 68.0},
    {"host": "server-04", "region": "hcm", "cpu_base": 28.0, "mem_base": 48.0},
    {"host": "server-05", "region": "hanoi", "cpu_base": 45.0, "mem_base": 62.0},
    {"host": "server-06", "region": "hanoi", "cpu_base": 38.0, "mem_base": 52.0},
    {"host": "server-07", "region": "hanoi", "cpu_base": 60.0, "mem_base": 75.0},
    {"host": "server-08", "region": "danang", "cpu_base": 30.0, "mem_base": 45.0},
    {"host": "server-09", "region": "danang", "cpu_base": 55.0, "mem_base": 70.0},
    {"host": "server-10", "region": "danang", "cpu_base": 40.0, "mem_base": 58.0},
]


def generate_server_metrics(server: Dict[str, Any], timestamp: datetime) -> Point:
    """Generate a single Point for a specific server node with realistic noise and spikes.

    Args:
        server: Dictionary containing host, region, and baseline metric values.
        timestamp: The UTC timestamp for this observation.

    Returns:
        Point: InfluxDB Point for 'server_metrics' measurement.
    """
    # CPU usage: baseline + random fluctuation [-8, +8] + occasional spike (+15-30 with 5% chance)
    cpu_spike = random.uniform(15.0, 30.0) if random.random() < 0.05 else 0.0
    cpu = server["cpu_base"] + random.uniform(-8.0, 8.0) + cpu_spike
    cpu = round(max(0.0, min(100.0, cpu)), 2)

    # Memory usage: baseline + random fluctuation [-4, +4] + gradual load variation
    mem_spike = random.uniform(5.0, 15.0) if random.random() < 0.05 else 0.0
    mem = server["mem_base"] + random.uniform(-4.0, 4.0) + mem_spike
    mem = round(max(0.0, min(100.0, mem)), 2)

    # Network in/out: positive float (MB/s)
    net_in = round(max(0.1, random.uniform(10.0, 120.0)), 2)
    net_out = round(max(0.1, random.uniform(5.0, 80.0)), 2)

    # Error rate (%): usually low (0.0 - 1.5%), with 5% probability of spike (2.0 - 9.5%)
    if random.random() < 0.05:
        err_rate = round(random.uniform(2.0, 9.5), 3)
    else:
        err_rate = round(random.uniform(0.0, 1.5), 3)
    err_rate = max(0.0, min(10.0, err_rate))

    return (
        Point("server_metrics")
        .tag("host", server["host"])
        .tag("region", server["region"])
        .field("cpu_usage", cpu)
        .field("memory_usage", mem)
        .field("network_in", net_in)
        .field("network_out", net_out)
        .field("error_rate", err_rate)
        .time(timestamp)
    )


def run_generator(interval: float = 1.0, iterations: int = 10, seed: int | None = None) -> None:
    """Run the time-series data generator loop.

    Args:
        interval: Delay in seconds between batches.
        iterations: Number of batches to write. If <= 0, runs indefinitely.
        seed: Optional random seed for reproducible runs.
    """
    if seed is not None:
        random.seed(seed)
        print(f"[INFO] Random seed initialized to: {seed}")

    # Load configuration
    try:
        cfg = InfluxDBConfig.load()
    except Exception as exc:
        print(f"[ERROR] Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Connecting to InfluxDB 3 Core (URL: {cfg.url})")
    print(f"[INFO] Target Database: {cfg.database}")
    print(f"[INFO] Servers: {len(SERVERS)} across 3 regions (hcm, hanoi, danang)")
    print(f"[INFO] Batch interval: {interval}s | Iterations: {'Infinite' if iterations <= 0 else iterations}")

    # Initialize client
    try:
        client = InfluxDBClient3(
            host=cfg.url,
            token=cfg.token,
            database=cfg.database,
            verify_ssl=False,
        )
    except Exception as exc:
        print(f"[ERROR] Failed to initialize InfluxDB 3 client for host {cfg.url}: {exc}", file=sys.stderr)
        sys.exit(1)

    batch_idx = 0
    total_points = 0

    try:
        while True:
            batch_idx += 1
            now = datetime.now(timezone.utc)
            points = [generate_server_metrics(server, now) for server in SERVERS]

            try:
                # Write batch to InfluxDB 3 Core
                client.write(record=points)
                total_points += len(points)
                iter_str = f"{batch_idx}/{iterations}" if iterations > 0 else f"{batch_idx}"
                print(f"[INFO] Iteration {iter_str} — wrote {len(points)} points (timestamp: {now.isoformat()})")
            except Exception as exc:
                print(f"[ERROR] Failed to write batch {batch_idx} to InfluxDB at {cfg.url}: {exc}", file=sys.stderr)
                sys.exit(1)

            if iterations > 0 and batch_idx >= iterations:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n[INFO] Data generation interrupted by user (SIGINT).")

    print(f"[INFO] Data generation completed successfully. Total points written: {total_points}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Time-Series Data Generator for InfluxDB 3 Core Server Telemetry."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Interval in seconds between generation batches (default: 1.0)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of iterations/batches to run. Set <= 0 for infinite streaming (default: 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible metrics",
    )

    args = parser.parse_args()
    run_generator(interval=args.interval, iterations=args.iterations, seed=args.seed)


if __name__ == "__main__":
    main()

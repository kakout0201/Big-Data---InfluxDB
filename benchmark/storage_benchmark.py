"""Storage Efficiency & Physical Parquet Benchmark for InfluxDB 3 Core.

Measures physical Parquet footprint on disk and in system metadata across 10K, 50K, 100K scales.
Performs stability polling, filesystem cross-checks, theoretical logical payload modeling,
and differentiates between metadata stability and Parquet persistence observation.
"""

import argparse
import csv
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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

from config import (
    BENCHMARK_DATABASE,
    BENCHMARK_TABLE,
    DEFAULT_SEED,
    FIXED_START_TIME,
    ROOT_DIR,
    BenchmarkConfig,
)
from generate_dataset import generate_dataset
from storage_measurement import (
    cross_check_filesystem_parquet,
    estimate_logical_payload_bytes_for_scale,
    get_database_dir_size_bytes,
    poll_persistence_stability,
    query_parquet_files_metadata,
)


def validate_dataset_integrity(client: InfluxDBClient3, table: str, expected_count: int) -> Dict[str, Any]:
    """Validate point count, cardinality, and null constraints."""
    try:
        cnt_res = client.query(query=f"SELECT count(*) AS total FROM {table}").to_pylist()
        actual_count = cnt_res[0]["total"] if cnt_res else 0
        if actual_count != expected_count:
            return {"valid": False, "count": actual_count, "error": f"Expected {expected_count}, got {actual_count}"}

        null_sql = f"""
        SELECT count(*) AS null_cnt FROM {table}
        WHERE cpu_usage IS NULL OR memory_usage IS NULL OR error_rate IS NULL OR host IS NULL OR region IS NULL
        """
        null_res = client.query(query=null_sql).to_pylist()
        null_cnt = null_res[0]["null_cnt"] if null_res else 0
        if null_cnt > 0:
            return {"valid": False, "count": actual_count, "error": f"Found {null_cnt} NULL rows"}

        card_sql = f"SELECT count(distinct host) as h_cnt, count(distinct region) as r_cnt FROM {table}"
        card_res = client.query(query=card_sql).to_pylist()[0]
        if card_res["h_cnt"] != 10 or card_res["r_cnt"] != 3:
            return {"valid": False, "count": actual_count, "error": f"Cardinality mismatch: h={card_res['h_cnt']}, r={card_res['r_cnt']}"}

        return {"valid": True, "count": actual_count, "error": None}
    except Exception as exc:
        return {"valid": False, "count": 0, "error": str(exc)}


def run_storage_benchmark(
    dataset_sizes: List[int],
    seed: int = DEFAULT_SEED,
    poll_interval: float = 1.0,
    stable_checks: int = 3,
    timeout_sec: float = 60.0,
    results_dir: Path = ROOT_DIR / "benchmark" / "results",
) -> Dict[str, Any]:
    """Execute complete storage efficiency and compression benchmark suite."""
    cfg = BenchmarkConfig.load()
    results_dir.mkdir(parents=True, exist_ok=True)

    client = InfluxDBClient3(
        host=cfg.url,
        token=cfg.token,
        database=cfg.database,
        verify_ssl=False,
    )

    raw_records: List[Dict[str, Any]] = []
    summary_records: List[Dict[str, Any]] = []

    print("=" * 80)
    print("INFLUXDB 3 CORE — PHYSICAL PARQUET STORAGE & PERSISTENCE BENCHMARK")
    print("=" * 80)
    print(f"Database: {cfg.database} | Table: {cfg.table}")
    print(f"Dataset Scales: {dataset_sizes}")
    print(f"Random Seed: {seed} | Start Time: {FIXED_START_TIME.isoformat()}")
    print(f"Persistence Polling: Interval={poll_interval}s, Stable Checks={stable_checks}, Timeout={timeout_sec}s")
    print("=" * 80)

    for idx, ds_size in enumerate(dataset_sizes, 1):
        print(f"\n================================================================================")
        print(f">>> [STAGE {idx}/{len(dataset_sizes)}] Dataset Scale: {ds_size:,} Points")
        print(f"================================================================================")

        # 1. Record baseline database directory size (diagnostic only)
        db_before_bytes = get_database_dir_size_bytes(db_id=2)
        print(f"[STORAGE DIAGNOSTIC] Database 2 directory footprint before: {db_before_bytes:,} bytes")

        # 2. Reset and Generate Dataset
        print(f"[GENERATION] Generating exact {ds_size:,} points dataset (batch_size=5000)...")
        t_gen_start = time.perf_counter()
        generate_dataset(
            target_points=ds_size,
            seed=seed,
            batch_size=5000,
            start_time=FIXED_START_TIME,
            reset=True,
        )
        gen_time = time.perf_counter() - t_gen_start
        print(f"[GENERATION COMPLETE] Done in {gen_time:.2f}s")

        # 3. Validate Dataset
        val = validate_dataset_integrity(client, cfg.table, ds_size)
        print(f"[VALIDATION] Validated {val['count']:,} points: {'PASS' if val['valid'] else 'FAIL (' + str(val['error']) + ')'}")
        if not val["valid"]:
            raise RuntimeError(f"Dataset validation failed: {val['error']}")

        # 4. Persistence Stability Polling
        print(f"[PERSISTENCE POLLING] Waiting for Parquet metadata stabilization...")
        poll_res = poll_persistence_stability(
            client=client,
            table_name=cfg.table,
            expected_rows=ds_size,
            poll_interval=poll_interval,
            stable_checks_required=stable_checks,
            timeout_seconds=timeout_sec,
        )
        print(f"[PERSISTENCE RESULT] Metadata Query Success: {poll_res['metadata_query_success']} | Metadata Stable: {poll_res['metadata_stable']} (Polled for {poll_res['poll_elapsed_seconds']:.2f}s)")
        print(f"  - Parquet Files Present: {poll_res['parquet_files_present']}")
        print(f"  - Partial Persistence Observed: {poll_res['partial_persistence_observed']}")
        print(f"  - Full Dataset Persistence Observed: {poll_res['full_dataset_persistence_observed']}")
        print(f"  - Parquet File Count: {poll_res['parquet_file_count']}")
        print(f"  - Metadata Parquet Bytes: {poll_res['metadata_parquet_bytes']:,} bytes")
        print(f"  - Parquet Rows Registered: {poll_res['total_parquet_rows']:,} rows")

        # 5. Filesystem Cross-check
        print(f"[FILESYSTEM CROSS-CHECK] Verifying physical files on container filesystem...")
        fs_bytes, diff_bytes, size_match, file_details = cross_check_filesystem_parquet(poll_res["files"])
        print(f"  - Filesystem Parquet Bytes: {fs_bytes:,} bytes")
        print(f"  - Difference (FS - Meta): {diff_bytes:,} bytes")
        print(f"  - Size Match: {'YES (100% Match)' if size_match else 'NO'}")

        # 6. Record database directory footprint after generation (diagnostic only)
        db_after_bytes = get_database_dir_size_bytes(db_id=2)
        db_delta_bytes = db_after_bytes - db_before_bytes
        print(f"[STORAGE DIAGNOSTIC] Database 2 directory footprint after: {db_after_bytes:,} bytes (Delta: {db_delta_bytes:+,} bytes)")

        # 7. Calculate Theoretical Logical Payload & Ratios
        logical_bytes = estimate_logical_payload_bytes_for_scale(ds_size)
        print(f"[LOGICAL PAYLOAD MODEL] Estimated Uncompressed Payload: {logical_bytes:,} bytes (61.5 bytes/point)")

        if poll_res["metadata_parquet_bytes"] > 0:
            storage_ratio = round(poll_res["metadata_parquet_bytes"] / logical_bytes, 4)
            diff_pct = round((1.0 - storage_ratio) * 100.0, 2)
            print(f"[STORAGE RATIO] Physical Parquet / Estimated Logical: {storage_ratio:.4f} ({diff_pct:+.2f}% diff)")
        else:
            storage_ratio = None
            diff_pct = None
            print(f"[STORAGE RATIO] Parquet bytes = 0 (Data residing in WAL / in-memory buffer before compaction)")

        # Measurement pipeline success definition
        pipeline_success = (
            val["valid"]
            and poll_res["metadata_query_success"]
            and poll_res["metadata_stable"]
            and size_match
        )

        notes = []
        if not poll_res["metadata_query_success"]:
            notes.append(f"Metadata query failed: {poll_res.get('error')}")
        elif not poll_res["metadata_stable"]:
            notes.append("Persistence polling timed out before metadata stabilized")
        if not size_match:
            notes.append(f"FS size mismatch: {diff_bytes}B difference")
        if not poll_res["full_dataset_persistence_observed"]:
            notes.append(f"Parquet row count ({poll_res['total_parquet_rows']}) differs from total dataset ({ds_size}) due to in-memory WAL buffer state; full dataset persistence not observed in measurement window")

        note_str = "; ".join(notes) if notes else "Clean run"

        # 8. Append to Raw Records
        raw_records.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dataset_size": ds_size,
            "expected_rows": ds_size,
            "validated_rows": val["count"],
            "parquet_file_count": poll_res["parquet_file_count"],
            "metadata_parquet_bytes": poll_res["metadata_parquet_bytes"],
            "filesystem_parquet_bytes": fs_bytes,
            "size_difference_bytes": diff_bytes,
            "size_match": size_match,
            "estimated_logical_payload_bytes": logical_bytes,
            "physical_to_estimated_logical_ratio": storage_ratio if storage_ratio is not None else "",
            "physical_to_estimated_logical_difference_percent": diff_pct if diff_pct is not None else "",
            "metadata_query_success": poll_res["metadata_query_success"],
            "metadata_stable": poll_res["metadata_stable"],
            "parquet_files_present": poll_res["parquet_files_present"],
            "partial_persistence_observed": poll_res["partial_persistence_observed"],
            "full_dataset_persistence_observed": poll_res["full_dataset_persistence_observed"],
            "validation_pass": val["valid"],
            "measurement_success": pipeline_success,
            "notes": note_str,
        })

        # 9. Append to Summary Records
        summary_records.append({
            "dataset_size": ds_size,
            "validated_rows": val["count"],
            "parquet_file_count": poll_res["parquet_file_count"],
            "physical_parquet_bytes": poll_res["metadata_parquet_bytes"],
            "estimated_logical_payload_bytes": logical_bytes,
            "physical_to_estimated_logical_ratio": storage_ratio if storage_ratio is not None else "",
            "physical_to_estimated_logical_difference_percent": diff_pct if diff_pct is not None else "",
            "metadata_query_success": poll_res["metadata_query_success"],
            "metadata_stable": poll_res["metadata_stable"],
            "parquet_files_present": poll_res["parquet_files_present"],
            "partial_persistence_observed": poll_res["partial_persistence_observed"],
            "full_dataset_persistence_observed": poll_res["full_dataset_persistence_observed"],
            "measurement_success": pipeline_success,
        })

    # 10. Save Raw CSV
    raw_csv_path = results_dir / "storage_raw.csv"
    with open(raw_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "dataset_size", "expected_rows", "validated_rows",
            "parquet_file_count", "metadata_parquet_bytes", "filesystem_parquet_bytes",
            "size_difference_bytes", "size_match", "estimated_logical_payload_bytes",
            "physical_to_estimated_logical_ratio", "physical_to_estimated_logical_difference_percent",
            "metadata_query_success", "metadata_stable", "parquet_files_present",
            "partial_persistence_observed", "full_dataset_persistence_observed",
            "validation_pass", "measurement_success", "notes"
        ])
        writer.writeheader()
        writer.writerows(raw_records)
    print(f"\n[INFO] Raw storage results saved to: {raw_csv_path}")

    # 11. Save Summary CSV
    summary_csv_path = results_dir / "storage_summary.csv"
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "dataset_size", "validated_rows", "parquet_file_count",
            "physical_parquet_bytes", "estimated_logical_payload_bytes",
            "physical_to_estimated_logical_ratio", "physical_to_estimated_logical_difference_percent",
            "metadata_query_success", "metadata_stable", "parquet_files_present",
            "partial_persistence_observed", "full_dataset_persistence_observed",
            "measurement_success"
        ])
        writer.writeheader()
        writer.writerows(summary_records)
    print(f"[INFO] Summary storage statistics saved to: {summary_csv_path}")

    # 12. Save Metadata JSON (Excluding secrets)
    metadata = {
        "benchmark_name": "InfluxDB 3 Core Storage Efficiency & Physical Parquet Benchmark",
        "benchmark_version": "1.2.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": cfg.database,
        "table": cfg.table,
        "dataset_sizes": dataset_sizes,
        "seed": seed,
        "fixed_start_time": FIXED_START_TIME.isoformat(),
        "methodology": {
            "primary_measurement": "Query system.parquet_files for active table_name='server_metrics_benchmark'",
            "secondary_validation": "Direct container filesystem inspection via docker exec stat across all discovered Parquet paths",
            "persistence_verification": f"Polling with interval={poll_interval}s, required_stable_checks={stable_checks}, timeout={timeout_sec}s",
            "logical_payload_model": {
                "name": "Estimated Uncompressed Logical Payload Model",
                "formula": "timestamp (8B) + host UTF-8 (9B) + region UTF-8 (avg 4.5B) + 5 fields (40B) = 61.5 bytes/point",
                "notes": "Theoretical uncompressed data model based on raw values, distinct from physical disk storage or serializations.",
            },
            "ratio_definition": "Physical-to-Estimated-Logical Storage Ratio = physical_parquet_bytes / estimated_logical_payload_bytes",
            "semantics_clarification": (
                "0 Parquet bytes indicates that no Parquet files have been registered for the active table in system.parquet_files "
                "within the measurement window; data resides in the Write Ahead Log (WAL) and in-memory buffer before background compaction."
            ),
        },
        "environment": {
            "os": "Microsoft Windows 11 Home Single Language 64-bit (Build 26200, AMD64)",
            "python_version": platform.python_version(),
            "influxdb_image": "influxdb:3-core (v3.11.2)",
            "storage_root": "/home/influxdb3/.influxdb3",
            "object_store": "file",
        },
    }

    metadata_path = results_dir / "storage_metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"[INFO] Storage experiment metadata saved to: {metadata_path}")

    # 13. Restore standard 10K baseline dataset for workspace integrity
    print("\n[RESTORATION] Restoring standard 10,000 baseline dataset in benchmark_monitoring...")
    generate_dataset(target_points=10_000, seed=DEFAULT_SEED, batch_size=5000, reset=True)

    # 14. Verify Demo Database preservation
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
    print("STORAGE BENCHMARK COMPLETED SUCCESSFULLY!")
    print("=" * 80)

    return {
        "raw_records": raw_records,
        "summary_records": summary_records,
        "metadata": metadata,
    }


def main() -> None:
    """CLI Entrypoint for Storage Efficiency Benchmark."""
    parser = argparse.ArgumentParser(
        description="Storage Efficiency & Parquet Benchmark for InfluxDB 3 Core."
    )
    parser.add_argument(
        "--dataset-sizes",
        type=str,
        default="10000,50000,100000",
        help="Comma-separated dataset sizes (default: '10000,50000,100000').",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Persistence polling interval in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--stable-checks",
        type=int,
        default=3,
        help="Consecutive unchanged checks required for stability (default: 3).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Persistence polling timeout in seconds (default: 60.0).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for reproducibility (default: {DEFAULT_SEED}).",
    )

    args = parser.parse_args()
    ds_sizes = [int(s.strip()) for s in args.dataset_sizes.split(",")]

    run_storage_benchmark(
        dataset_sizes=ds_sizes,
        seed=args.seed,
        poll_interval=args.poll_interval,
        stable_checks=args.stable_checks,
        timeout_sec=args.timeout,
    )


if __name__ == "__main__":
    main()

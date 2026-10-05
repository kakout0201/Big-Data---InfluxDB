"""Storage Measurement & Physical Parquet Discovery Utility for InfluxDB 3 Core.

Provides low-level functions for:
- Querying system.parquet_files metadata with explicit error handling
- Cross-checking file sizes against the container filesystem
- Persistence stability polling with distinct metadata and persistence states
- Theoretical uncompressed logical payload calculation
- Physical-to-Estimated-Logical storage ratio calculation
"""

import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from influxdb_client_3 import InfluxDBClient3

from config import BENCHMARK_TABLE


def calculate_logical_payload_bytes_exact(points: List[Dict[str, Any]]) -> int:
    """Calculate exact uncompressed logical payload size in bytes from generated point dicts.

    Theoretical Model Specification:
    - timestamp: 8 bytes (Int64 UTC nanoseconds)
    - host tag: UTF-8 encoded byte length (e.g. 'server-01' -> 9 bytes)
    - region tag: UTF-8 encoded byte length (e.g. 'hcm' -> 3 bytes, 'hanoi' -> 5 bytes, 'danang' -> 6 bytes)
    - 5 numeric fields (cpu_usage, memory_usage, network_in, network_out, error_rate): 5 * 8 = 40 bytes (Float64)
    """
    total_bytes = 0
    for p in points:
        host_bytes = len(str(p.get("host", "")).encode("utf-8"))
        region_bytes = len(str(p.get("region", "")).encode("utf-8"))
        total_bytes += 8 + 40 + host_bytes + region_bytes
    return total_bytes


def estimate_logical_payload_bytes_for_scale(total_points: int) -> int:
    """Calculate deterministic uncompressed logical payload size for a given scale.

    Theoretical Model Distribution:
    - 10 hosts ('server-01'..'server-10'): 9 bytes each -> 9.0 bytes avg
    - 3 regions: 'hcm' (3 bytes, 40%), 'hanoi' (5 bytes, 30%), 'danang' (6 bytes, 30%)
      Weighted average region bytes = 0.4*3 + 0.3*5 + 0.3*6 = 1.2 + 1.5 + 1.8 = 4.5 bytes
    - timestamp (8 bytes) + fields (40 bytes) + host (9 bytes) + region (4.5 bytes) = 61.5 bytes/point
    """
    return int(total_points * 61.5)


# Alias for backward compatibility
calculate_logical_payload_for_scale = estimate_logical_payload_bytes_for_scale


def query_parquet_files_metadata(
    client: InfluxDBClient3,
    table_name: str = BENCHMARK_TABLE,
) -> Dict[str, Any]:
    """Query system.parquet_files for a specific table name.

    Returns:
        Dict with keys:
        - query_success (bool): True if SQL query executed and returned cleanly.
        - table_name (str)
        - parquet_file_count (int)
        - metadata_parquet_bytes (int)
        - total_parquet_rows (int)
        - files (List[Dict])
        - error (Optional[str])
    """
    sql = f"""
    SELECT
        table_name,
        path,
        size_bytes,
        row_count,
        min_time,
        max_time
    FROM system.parquet_files
    WHERE table_name = '{table_name}'
    ORDER BY path
    """
    try:
        reader = client.query(query=sql)
        rows = reader.to_pylist()
        total_bytes = sum(int(r.get("size_bytes", 0)) for r in rows)
        total_rows = sum(int(r.get("row_count", 0)) for r in rows)
        return {
            "query_success": True,
            "table_name": table_name,
            "parquet_file_count": len(rows),
            "metadata_parquet_bytes": total_bytes,
            "total_parquet_rows": total_rows,
            "files": rows,
            "error": None,
        }
    except Exception as exc:
        return {
            "query_success": False,
            "table_name": table_name,
            "parquet_file_count": 0,
            "metadata_parquet_bytes": 0,
            "total_parquet_rows": 0,
            "files": [],
            "error": str(exc),
        }


def cross_check_filesystem_parquet(
    files: List[Dict[str, Any]],
    container_name: str = "influxdb3-core",
    storage_root: str = "/home/influxdb3/.influxdb3",
) -> Tuple[int, int, bool, List[Dict[str, Any]]]:
    """Inspect actual physical files on container filesystem and cross-check against metadata.

    Returns:
        (total_filesystem_bytes, size_difference_bytes, size_match_bool, file_details)
    """
    if not files:
        return 0, 0, True, []

    total_fs_bytes = 0
    file_details: List[Dict[str, Any]] = []
    all_matched = True

    for f in files:
        rel_path = f.get("path", "")
        meta_size = int(f.get("size_bytes", 0))
        full_container_path = f"{storage_root}/{rel_path}"

        try:
            cmd = ["docker", "exec", container_name, "stat", "-c", "%s", full_container_path]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            fs_size = int(res.stdout.strip())
        except Exception:
            fs_size = -1
            all_matched = False

        diff = fs_size - meta_size if fs_size >= 0 else -1
        match = (diff == 0)
        if not match:
            all_matched = False

        total_fs_bytes += max(0, fs_size)
        file_details.append({
            "path": rel_path,
            "metadata_size_bytes": meta_size,
            "filesystem_size_bytes": fs_size,
            "row_count": f.get("row_count", 0),
            "size_match": match,
            "difference_bytes": diff,
        })

    diff_total = total_fs_bytes - sum(int(f.get("size_bytes", 0)) for f in files)
    return total_fs_bytes, diff_total, all_matched, file_details


def get_database_dir_size_bytes(
    db_id: int = 2,
    container_name: str = "influxdb3-core",
    storage_root: str = "/home/influxdb3/.influxdb3",
) -> int:
    """Read total physical size of database directory (e.g. node0/dbs/2) via du.

    Note: Diagnostic baseline only; includes soft-deleted tables and database-level files.
    """
    dir_path = f"{storage_root}/node0/dbs/{db_id}"
    try:
        cmd = ["docker", "exec", container_name, "du", "-sb", dir_path]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        size_str = res.stdout.strip().split()[0]
        return int(size_str)
    except Exception:
        return 0


def poll_persistence_stability(
    client: InfluxDBClient3,
    table_name: str = BENCHMARK_TABLE,
    expected_rows: Optional[int] = None,
    poll_interval: float = 1.0,
    stable_checks_required: int = 3,
    timeout_seconds: float = 60.0,
) -> Dict[str, Any]:
    """Poll system.parquet_files until metadata remains unchanged for N consecutive checks.

    Distinguishes:
    - metadata_query_success: True when SQL queries to system.parquet_files succeed.
    - metadata_stable: True when Parquet metadata state did not change across N checks.
    - parquet_files_present: True when parquet_file_count > 0.
    - partial_persistence_observed: True when 0 < total_parquet_rows < expected_rows.
    - full_dataset_persistence_observed: True when parquet_file_count > 0 and total_parquet_rows == expected_rows.

    Returns:
        Dict containing the evaluated state machine flags and metrics.
    """
    t_start = time.perf_counter()
    last_state = None
    consecutive_stable_count = 0
    last_meta: Optional[Dict[str, Any]] = None

    while True:
        elapsed = time.perf_counter() - t_start
        meta = query_parquet_files_metadata(client, table_name)
        last_meta = meta

        if not meta["query_success"]:
            # Query error occurred: fail stability immediately
            return {
                "metadata_query_success": False,
                "metadata_stable": False,
                "parquet_files_present": False,
                "partial_persistence_observed": False,
                "full_dataset_persistence_observed": False,
                "parquet_file_count": 0,
                "metadata_parquet_bytes": 0,
                "total_parquet_rows": 0,
                "files": [],
                "poll_elapsed_seconds": round(elapsed, 3),
                "error": meta.get("error"),
            }

        current_state = (
            meta["parquet_file_count"],
            meta["metadata_parquet_bytes"],
            meta["total_parquet_rows"],
        )

        if current_state == last_state and last_state is not None:
            consecutive_stable_count += 1
            if consecutive_stable_count >= stable_checks_required:
                files_present = meta["parquet_file_count"] > 0
                parquet_rows = meta["total_parquet_rows"]

                if expected_rows is not None:
                    partial_observed = files_present and (0 < parquet_rows < expected_rows)
                    full_observed = files_present and (parquet_rows == expected_rows)
                else:
                    partial_observed = False
                    full_observed = files_present and (parquet_rows > 0)

                return {
                    "metadata_query_success": True,
                    "metadata_stable": True,
                    "parquet_files_present": files_present,
                    "partial_persistence_observed": partial_observed,
                    "full_dataset_persistence_observed": full_observed,
                    "parquet_file_count": meta["parquet_file_count"],
                    "metadata_parquet_bytes": meta["metadata_parquet_bytes"],
                    "total_parquet_rows": parquet_rows,
                    "files": meta["files"],
                    "poll_elapsed_seconds": round(elapsed, 3),
                    "error": None,
                }
        else:
            consecutive_stable_count = 1
            last_state = current_state

        if elapsed >= timeout_seconds:
            files_present = meta["parquet_file_count"] > 0
            parquet_rows = meta["total_parquet_rows"]

            if expected_rows is not None:
                partial_observed = files_present and (0 < parquet_rows < expected_rows)
                full_observed = files_present and (parquet_rows == expected_rows)
            else:
                partial_observed = False
                full_observed = files_present and (parquet_rows > 0)

            return {
                "metadata_query_success": True,
                "metadata_stable": False,
                "parquet_files_present": files_present,
                "partial_persistence_observed": partial_observed,
                "full_dataset_persistence_observed": full_observed,
                "parquet_file_count": meta["parquet_file_count"],
                "metadata_parquet_bytes": meta["metadata_parquet_bytes"],
                "total_parquet_rows": parquet_rows,
                "files": meta["files"],
                "poll_elapsed_seconds": round(elapsed, 3),
                "error": "Polling timeout reached before metadata stabilized",
            }

        time.sleep(poll_interval)

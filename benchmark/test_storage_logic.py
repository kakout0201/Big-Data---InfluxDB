"""Unit & Smoke Test Suite for Storage Measurement Logic & State Machine (Task 9.2).

Validates all 6 core experimental methodology requirements without modifying database state:
- Test 1: Metadata query success
- Test 2: Metadata query failure & error propagation (cannot become false 0-parquet success)
- Test 3: Stable empty state (metadata_stable=True, parquet_files_present=False, full_persistence=False)
- Test 4: Partial persistence detection (0 < rows < expected)
- Test 5: Full dataset persistence detection (rows == expected)
- Test 6: Filesystem cross-check size mismatch handling
- Test 7: Logical payload calculation consistency
"""

import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from storage_measurement import (
    calculate_logical_payload_bytes_exact,
    cross_check_filesystem_parquet,
    estimate_logical_payload_bytes_for_scale,
    poll_persistence_stability,
    query_parquet_files_metadata,
)


def test_1_metadata_query_success():
    """Test 1: Clean SQL query execution returns query_success=True."""
    mock_client = MagicMock()
    mock_reader = MagicMock()
    mock_reader.to_pylist.return_value = [
        {"table_name": "test_tbl", "path": "node0/dbs/2/1.parquet", "size_bytes": 1000, "row_count": 500, "min_time": 0, "max_time": 10}
    ]
    mock_client.query.return_value = mock_reader

    res = query_parquet_files_metadata(mock_client, "test_tbl")
    assert res["query_success"] is True, "Expected query_success=True"
    assert res["parquet_file_count"] == 1
    assert res["metadata_parquet_bytes"] == 1000
    assert res["total_parquet_rows"] == 500
    assert res["error"] is None
    print("[PASS] Test 1: Metadata query success handled correctly.")


def test_2_metadata_query_failure():
    """Test 2: SQL query failure returns query_success=False and captures error."""
    mock_client = MagicMock()
    mock_client.query.side_effect = RuntimeError("Connection dropped or table missing")

    res = query_parquet_files_metadata(mock_client, "test_tbl")
    assert res["query_success"] is False, "Expected query_success=False on exception"
    assert res["error"] == "Connection dropped or table missing"
    assert res["parquet_file_count"] == 0

    # Test polling with failed query
    poll_res = poll_persistence_stability(mock_client, "test_tbl", expected_rows=10000, timeout_seconds=1.0)
    assert poll_res["metadata_query_success"] is False, "Expected metadata_query_success=False"
    assert poll_res["metadata_stable"] is False, "Failed query cannot be considered stable"
    assert poll_res["parquet_files_present"] is False
    assert poll_res["full_dataset_persistence_observed"] is False

    # Verify measurement_success flag would be False
    validation_pass = True
    size_match = True
    measurement_success = validation_pass and poll_res["metadata_query_success"] and poll_res["metadata_stable"] and size_match
    assert measurement_success is False, "Measurement must fail when query fails"
    print("[PASS] Test 2: Metadata query failure correctly marked as measurement failure.")


def test_3_stable_empty_state():
    """Test 3: Stable 0-files state yields metadata_stable=True, but parquet_files_present=False."""
    mock_client = MagicMock()
    mock_reader = MagicMock()
    mock_reader.to_pylist.return_value = []
    mock_client.query.return_value = mock_reader

    poll_res = poll_persistence_stability(
        mock_client,
        "test_tbl",
        expected_rows=10000,
        poll_interval=0.01,
        stable_checks_required=3,
        timeout_seconds=2.0,
    )
    assert poll_res["metadata_query_success"] is True
    assert poll_res["metadata_stable"] is True, "Expected metadata_stable=True for 3 consecutive identical reads"
    assert poll_res["parquet_files_present"] is False
    assert poll_res["partial_persistence_observed"] is False
    assert poll_res["full_dataset_persistence_observed"] is False
    assert poll_res["parquet_file_count"] == 0
    assert poll_res["total_parquet_rows"] == 0
    print("[PASS] Test 3: Stable empty state distinguished from persistence observation.")


def test_4_partial_persistence():
    """Test 4: Parquet rows < expected rows yields partial_persistence_observed=True."""
    mock_client = MagicMock()
    mock_reader = MagicMock()
    mock_reader.to_pylist.return_value = [
        {"table_name": "test_tbl", "path": "node0/dbs/2/1.parquet", "size_bytes": 5000, "row_count": 50000, "min_time": 0, "max_time": 10}
    ]
    mock_client.query.return_value = mock_reader

    poll_res = poll_persistence_stability(
        mock_client,
        "test_tbl",
        expected_rows=100000,
        poll_interval=0.01,
        stable_checks_required=3,
        timeout_seconds=2.0,
    )
    assert poll_res["metadata_stable"] is True
    assert poll_res["parquet_files_present"] is True
    assert poll_res["partial_persistence_observed"] is True, "50K/100K should be partial persistence"
    assert poll_res["full_dataset_persistence_observed"] is False
    print("[PASS] Test 4: Partial persistence correctly identified.")


def test_5_full_persistence():
    """Test 5: Parquet rows == expected rows yields full_dataset_persistence_observed=True."""
    mock_client = MagicMock()
    mock_reader = MagicMock()
    mock_reader.to_pylist.return_value = [
        {"table_name": "test_tbl", "path": "node0/dbs/2/1.parquet", "size_bytes": 10000, "row_count": 100000, "min_time": 0, "max_time": 10}
    ]
    mock_client.query.return_value = mock_reader

    poll_res = poll_persistence_stability(
        mock_client,
        "test_tbl",
        expected_rows=100000,
        poll_interval=0.01,
        stable_checks_required=3,
        timeout_seconds=2.0,
    )
    assert poll_res["metadata_stable"] is True
    assert poll_res["parquet_files_present"] is True
    assert poll_res["partial_persistence_observed"] is False
    assert poll_res["full_dataset_persistence_observed"] is True, "100K/100K should be full persistence"
    print("[PASS] Test 5: Full dataset persistence correctly identified.")


def test_6_filesystem_mismatch():
    """Test 6: Filesystem size mismatch yields size_match=False and measurement failure."""
    files = [{"path": "node0/dbs/2/1.parquet", "size_bytes": 5000, "row_count": 100}]

    # Mock docker exec stat returning 4500 (mismatch)
    with patch("subprocess.run") as mock_sub:
        mock_res = MagicMock()
        mock_res.stdout = "4500\n"
        mock_sub.return_value = mock_res

        total_fs, diff, match, details = cross_check_filesystem_parquet(files)
        assert match is False, "Expected match=False on size discrepancy"
        assert diff == -500
        assert total_fs == 4500

        # Measurement pipeline evaluation
        validation_pass = True
        metadata_query_success = True
        metadata_stable = True
        size_match = match
        measurement_success = validation_pass and metadata_query_success and metadata_stable and size_match
        assert measurement_success is False, "Measurement must fail when filesystem mismatch occurs"
    print("[PASS] Test 6: Filesystem size mismatch triggers failure.")


def test_7_logical_payload_model():
    """Test 7: Logical payload model calculates 61.5 bytes/point deterministically."""
    # 10,000 points model
    scaled_10k = estimate_logical_payload_bytes_for_scale(10000)
    assert scaled_10k == 615000, f"Expected 615,000 bytes, got {scaled_10k}"

    # Verify point-by-point calculation
    sample_points = [
        {"host": "server-01", "region": "hcm"},    # 8 + 40 + 9 + 3 = 60
        {"host": "server-02", "region": "hanoi"},  # 8 + 40 + 9 + 5 = 62
        {"host": "server-03", "region": "danang"}, # 8 + 40 + 9 + 6 = 63
    ]
    exact_bytes = calculate_logical_payload_bytes_exact(sample_points)
    assert exact_bytes == 60 + 62 + 63, f"Expected 185 bytes, got {exact_bytes}"
    print("[PASS] Test 7: Logical payload theoretical model verified.")


def main():
    print("=" * 70)
    print("RUNNING UNIT & SMOKE TESTS FOR STORAGE BENCHMARK LOGIC (TASK 9.2)")
    print("=" * 70)
    test_1_metadata_query_success()
    test_2_metadata_query_failure()
    test_3_stable_empty_state()
    test_4_partial_persistence()
    test_5_full_persistence()
    test_6_filesystem_mismatch()
    test_7_logical_payload_model()
    print("=" * 70)
    print("ALL 7 UNIT & SMOKE TESTS PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""Benchmark Configuration Module for InfluxDB 3.

Defines target database, table, server metadata, default experiment parameters,
and secure credentials loader for the controlled benchmark framework.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from dotenv import load_dotenv

# Locate project root and .env file
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()

# Database & Table Constants
BENCHMARK_DATABASE = "benchmark_monitoring"
BENCHMARK_TABLE = "server_metrics_benchmark"

# Experiment & Generation Defaults
DEFAULT_SEED = 42
DEFAULT_BATCH_SIZE = 1000
SUPPORTED_DATASET_SIZES = [10_000, 50_000, 100_000, 500_000, 1_000_000]

# Fixed Start Time for 100% Reproducibility (within retention window)
FIXED_START_TIME = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
ROUND_INTERVAL_SECONDS = 10

# Fixed Server Distribution (10 Servers across 3 Regions)
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


@dataclass(frozen=True)
class BenchmarkConfig:
    """Benchmark connection and execution parameters."""

    url: str
    token: str
    database: str = BENCHMARK_DATABASE
    table: str = BENCHMARK_TABLE

    @classmethod
    def load(cls) -> "BenchmarkConfig":
        """Load and validate credentials from environment securely."""
        url = os.getenv("INFLUXDB_URL", "https://localhost:8181").strip()
        token = os.getenv("INFLUXDB_TOKEN", "").strip()

        if not token:
            raise ValueError(
                "INFLUXDB_TOKEN is not configured! "
                "Please verify INFLUXDB_TOKEN in your .env file."
            )

        return cls(url=url, token=token)

    def sanitized_summary(self) -> str:
        """Return a string summary of the configuration with token masked."""
        return (
            f"BenchmarkConfig(url='{self.url}', database='{self.database}', "
            f"table='{self.table}', token='***[MASKED]***')"
        )

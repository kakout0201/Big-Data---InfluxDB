"""SQL Query Definitions for InfluxDB 3 Core Query Latency Benchmark.

Defines 4 standardized query groups:
- Q1: COUNT (Full dataset aggregate)
- Q2: AVG CPU BY HOST (Group By on Tag dimension)
- Q3: TIME-SERIES AGGREGATION (date_bin windowing)
- Q4: FILTER + AGGREGATION (Tag filtering + Multi-metric aggregate)
"""

from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass(frozen=True)
class BenchmarkQuery:
    """Represents a standardized benchmark query."""

    query_id: str
    name: str
    description: str
    sql: str
    expected_min_rows: int = 1
    validator: Optional[Callable[[List[dict]], bool]] = None


# Query Definitions
QUERIES: List[BenchmarkQuery] = [
    BenchmarkQuery(
        query_id="Q1",
        name="COUNT",
        description="Simple full-table count aggregate",
        sql="SELECT COUNT(*) AS total_records FROM server_metrics_benchmark",
        expected_min_rows=1,
        validator=lambda rows: len(rows) == 1 and rows[0].get("total_records", 0) > 0,
    ),
    BenchmarkQuery(
        query_id="Q2",
        name="AVG_CPU_BY_HOST",
        description="Dimension group by and aggregation on host tag",
        sql="""
        SELECT
            host,
            AVG(cpu_usage) AS avg_cpu
        FROM server_metrics_benchmark
        GROUP BY host
        ORDER BY avg_cpu DESC
        """.strip(),
        expected_min_rows=10,
        validator=lambda rows: len(rows) == 10,
    ),
    BenchmarkQuery(
        query_id="Q3",
        name="TIME_SERIES_AGGREGATION",
        description="Time-windowed aggregation using date_bin (5 minutes)",
        sql="""
        SELECT
            date_bin(INTERVAL '5 minutes', time) AS time_bucket,
            AVG(cpu_usage) AS avg_cpu
        FROM server_metrics_benchmark
        GROUP BY time_bucket
        ORDER BY time_bucket
        """.strip(),
        expected_min_rows=1,
        validator=lambda rows: len(rows) > 0 and "time_bucket" in rows[0],
    ),
    BenchmarkQuery(
        query_id="Q4",
        name="FILTER_AGGREGATION",
        description="Tag filtered multi-metric aggregation (region='hcm')",
        sql="""
        SELECT
            region,
            AVG(cpu_usage) AS avg_cpu,
            AVG(memory_usage) AS avg_memory,
            AVG(error_rate) AS avg_error_rate
        FROM server_metrics_benchmark
        WHERE region = 'hcm'
        GROUP BY region
        """.strip(),
        expected_min_rows=1,
        validator=lambda rows: len(rows) == 1 and rows[0].get("region") == "hcm",
    ),
]

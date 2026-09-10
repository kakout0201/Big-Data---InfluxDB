-- ============================================================================
-- 03_time_series.sql: Time-Series Trend & Anomaly Detection Queries
-- Database: server_monitoring | Table: server_metrics
-- ============================================================================

-- Query 11: CPU usage trend over time by server (chronological order)
SELECT
    time,
    host,
    cpu_usage
FROM server_metrics
ORDER BY time ASC;

-- Query 12: Memory usage trend over time by server (chronological order)
SELECT
    time,
    host,
    memory_usage
FROM server_metrics
ORDER BY time ASC;

-- Query 13: Time-bucketed average CPU usage using Apache DataFusion date_bin
-- Aggregates data into 5-second fixed windows from Unix epoch origin
SELECT
    date_bin(INTERVAL '5 seconds', time, TIMESTAMP '1970-01-01 00:00:00Z') AS time_bucket,
    avg(cpu_usage) AS avg_cpu
FROM server_metrics
GROUP BY time_bucket
ORDER BY time_bucket ASC;

-- Query 14: High CPU threshold anomaly detection (> 80.0%)
SELECT
    time,
    host,
    region,
    cpu_usage
FROM server_metrics
WHERE cpu_usage > 80.0
ORDER BY time DESC;

-- Query 15: High memory threshold anomaly detection (> 80.0%)
SELECT
    time,
    host,
    region,
    memory_usage
FROM server_metrics
WHERE memory_usage > 80.0
ORDER BY time DESC;

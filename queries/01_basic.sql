-- ============================================================================
-- 01_basic.sql: Basic InfluxDB 3 SQL Queries for Server Telemetry Inspection
-- Database: server_monitoring | Table: server_metrics
-- ============================================================================

-- Query 1: Count total records in server_metrics
SELECT count(*) AS total_records
FROM server_metrics;

-- Query 2: Inspect 10 most recent telemetry records across all metrics
SELECT
    time,
    host,
    region,
    cpu_usage,
    memory_usage,
    network_in,
    network_out,
    error_rate
FROM server_metrics
ORDER BY time DESC
LIMIT 10;

-- Query 3: List all distinct server hostnames
SELECT DISTINCT host
FROM server_metrics
ORDER BY host ASC;

-- Query 4: List all distinct geographic regions
SELECT DISTINCT region
FROM server_metrics
ORDER BY region ASC;

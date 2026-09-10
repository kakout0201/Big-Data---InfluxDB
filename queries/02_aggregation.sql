-- ============================================================================
-- 02_aggregation.sql: Aggregation & Summary Analytics for InfluxDB 3
-- Database: server_monitoring | Table: server_metrics
-- ============================================================================

-- Query 5: Average CPU usage across the entire system
SELECT avg(cpu_usage) AS avg_cpu_usage
FROM server_metrics;

-- Query 6: Average CPU usage grouped by server host (ordered descending)
SELECT
    host,
    avg(cpu_usage) AS avg_cpu
FROM server_metrics
GROUP BY host
ORDER BY avg_cpu DESC;

-- Query 7: Average memory usage grouped by geographic region
SELECT
    region,
    avg(memory_usage) AS avg_memory
FROM server_metrics
GROUP BY region
ORDER BY avg_memory DESC;

-- Query 8: Maximum CPU usage observed per server
SELECT
    host,
    max(cpu_usage) AS max_cpu
FROM server_metrics
GROUP BY host
ORDER BY max_cpu DESC;

-- Query 9: Average error rate percentage grouped by region
SELECT
    region,
    avg(error_rate) AS avg_error_rate
FROM server_metrics
GROUP BY region
ORDER BY avg_error_rate DESC;

-- Query 10: Top 5 servers with highest average CPU usage
SELECT
    host,
    avg(cpu_usage) AS avg_cpu
FROM server_metrics
GROUP BY host
ORDER BY avg_cpu DESC
LIMIT 5;

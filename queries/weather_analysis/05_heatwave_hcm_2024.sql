-- ============================================================================
-- 05_heatwave_hcm_2024.sql: Đợt nắng nóng TP.HCM tháng 04-05/2024 — bối cảnh cho P7
-- Database: weather | Table: weather_hourly | location = 'hcm'
-- Mục đích: xác định cửa sổ sự kiện (ground truth) và kiểm tra dữ liệu mô hình có
-- thể hiện được đợt nắng nóng không, trước khi dùng nó để đánh giá phát hiện bất thường.
-- Chạy: python python/run_sql.py queries/weather_analysis/05_heatwave_hcm_2024.sql --max-rows 70
-- ============================================================================

-- Query 1: Nhiệt độ cao nhất ngày tại TP.HCM, 01/04 - 31/05/2024 (giờ địa phương)
SELECT
    date_bin(INTERVAL '1 day', time + INTERVAL '7 hours', TIMESTAMP '2024-01-01T00:00:00Z') AS day_local,
    round(max(temperature_c), 1) AS max_c,
    round(min(temperature_c), 1) AS min_c,
    round(avg(humidity_pct), 1) AS avg_rh,
    round(sum(precipitation_mm), 1) AS rain_mm
FROM weather_hourly
WHERE location = 'hcm'
  AND time >= TIMESTAMP '2024-03-31T17:00:00Z'      -- 2024-04-01 00:00 giờ VN
  AND time <  TIMESTAMP '2024-05-31T17:00:00Z'      -- 2024-06-01 00:00 giờ VN
GROUP BY day_local
ORDER BY day_local;

-- Query 2: So sánh tháng 4 và tháng 5 giữa các năm có dữ liệu (2024, 2025, 2026)
SELECT
    date_part('year', time + INTERVAL '7 hours') AS year_local,
    date_part('month', time + INTERVAL '7 hours') AS month_local,
    round(avg(temperature_c), 2) AS avg_c,
    round(max(temperature_c), 1) AS max_c,
    round(approx_percentile_cont(temperature_c, 0.95), 1) AS p95_c,
    sum(CASE WHEN temperature_c >= 35 THEN 1 ELSE 0 END) AS hours_ge_35c,
    round(sum(precipitation_mm), 0) AS rain_mm
FROM weather_hourly
WHERE location = 'hcm'
  AND date_part('month', time + INTERVAL '7 hours') IN (4, 5)
GROUP BY year_local, month_local
ORDER BY month_local, year_local;

-- Query 3: 10 giờ nóng nhất trong toàn bộ dữ liệu TP.HCM
SELECT time + INTERVAL '7 hours' AS time_local, temperature_c, humidity_pct, dew_point_c
FROM weather_hourly
WHERE location = 'hcm'
ORDER BY temperature_c DESC
LIMIT 10;

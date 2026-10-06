-- ============================================================================
-- 03_yagi_hanoi.sql: Bão Yagi tại Hà Nội — tương quan gió, mưa, áp suất (P6)
-- Database: weather | Table: weather_hourly | location = 'hanoi'
-- Cửa sổ sự kiện: 2024-09-06 00:00 → 2024-09-09 00:00 giờ VN (UTC+7)
--                = 2024-09-05T17:00Z → 2024-09-08T17:00Z
-- Cửa sổ tham chiếu: tháng 08/2024 (cùng mùa, không có bão lớn)
-- Chạy: python python/run_sql.py queries/weather_analysis/03_yagi_hanoi.sql --max-rows 80
-- ============================================================================

-- Query 1: Chuỗi theo giờ quanh sự kiện — áp suất, biến thiên áp 3 giờ, gió, mưa cộng dồn
-- dp_3h_hpa = áp suất hiện tại - áp suất 3 giờ trước (âm mạnh = áp thấp đang tiến đến)
SELECT
    time + INTERVAL '7 hours' AS time_local,
    pressure_msl_hpa AS hpa,
    round(pressure_msl_hpa - lag(pressure_msl_hpa, 3) OVER (ORDER BY time), 1) AS dp_3h_hpa,
    wind_speed_ms AS wind_ms,
    wind_gusts_ms AS gust_ms,
    wind_direction_deg AS dir_deg,
    precipitation_mm AS rain_mm,
    round(sum(precipitation_mm) OVER (ORDER BY time ROWS UNBOUNDED PRECEDING), 1) AS rain_cum_mm,
    weather_code
FROM weather_hourly
WHERE location = 'hanoi'
  AND time >= TIMESTAMP '2024-09-05T17:00:00Z'
  AND time <  TIMESTAMP '2024-09-08T17:00:00Z'
ORDER BY time;

-- Query 2: Thời điểm áp suất thấp nhất (tâm bão gần nhất)
SELECT time + INTERVAL '7 hours' AS time_local, pressure_msl_hpa, wind_speed_ms, wind_gusts_ms
FROM weather_hourly
WHERE location = 'hanoi'
  AND time >= TIMESTAMP '2024-09-05T17:00:00Z' AND time < TIMESTAMP '2024-09-08T17:00:00Z'
ORDER BY pressure_msl_hpa ASC
LIMIT 1;

-- Query 3: Thời điểm gió giật mạnh nhất
SELECT time + INTERVAL '7 hours' AS time_local, wind_gusts_ms, wind_speed_ms, pressure_msl_hpa
FROM weather_hourly
WHERE location = 'hanoi'
  AND time >= TIMESTAMP '2024-09-05T17:00:00Z' AND time < TIMESTAMP '2024-09-08T17:00:00Z'
ORDER BY wind_gusts_ms DESC
LIMIT 1;

-- Query 4: Sự kiện so với tham chiếu tháng 08/2024 — mức độ bất thường
SELECT
    period,
    count(*) AS hours,
    round(avg(pressure_msl_hpa), 1) AS avg_hpa,
    round(min(pressure_msl_hpa), 1) AS min_hpa,
    round(avg(wind_speed_ms), 2) AS avg_wind_ms,
    round(max(wind_gusts_ms), 1) AS max_gust_ms,
    round(sum(precipitation_mm), 1) AS rain_mm,
    round(sum(precipitation_mm) / count(*) * 24, 1) AS rain_mm_per_day
FROM (
    SELECT 'reference_2024_08' AS period, * FROM weather_hourly
    WHERE location = 'hanoi'
      AND time >= TIMESTAMP '2024-07-31T17:00:00Z' AND time < TIMESTAMP '2024-08-31T17:00:00Z'
    UNION ALL
    SELECT 'yagi_2024_09_06_08' AS period, * FROM weather_hourly
    WHERE location = 'hanoi'
      AND time >= TIMESTAMP '2024-09-05T17:00:00Z' AND time < TIMESTAMP '2024-09-08T17:00:00Z'
) AS w
GROUP BY period
ORDER BY period;

-- Query 5: Hệ số tương quan Pearson giữa áp suất, gió, mưa — sự kiện vs tham chiếu
-- Kỳ vọng: trong bão, áp suất giảm khi gió tăng => corr(áp suất, gió) âm mạnh
SELECT
    period,
    round(corr(pressure_msl_hpa, wind_speed_ms), 3) AS r_pressure_wind,
    round(corr(pressure_msl_hpa, wind_gusts_ms), 3) AS r_pressure_gust,
    round(corr(pressure_msl_hpa, precipitation_mm), 3) AS r_pressure_rain,
    round(corr(wind_speed_ms, precipitation_mm), 3) AS r_wind_rain
FROM (
    SELECT 'reference_2024_08' AS period, * FROM weather_hourly
    WHERE location = 'hanoi'
      AND time >= TIMESTAMP '2024-07-31T17:00:00Z' AND time < TIMESTAMP '2024-08-31T17:00:00Z'
    UNION ALL
    SELECT 'yagi_2024_09_06_08' AS period, * FROM weather_hourly
    WHERE location = 'hanoi'
      AND time >= TIMESTAMP '2024-09-05T17:00:00Z' AND time < TIMESTAMP '2024-09-08T17:00:00Z'
) AS w
GROUP BY period
ORDER BY period;

-- Query 6: Xếp hạng — áp suất thấp nhất và gió giật mạnh nhất của Hà Nội có nằm trong Yagi không?
SELECT
    time + INTERVAL '7 hours' AS time_local,
    pressure_msl_hpa,
    wind_gusts_ms,
    precipitation_mm
FROM weather_hourly
WHERE location = 'hanoi'
ORDER BY pressure_msl_hpa ASC
LIMIT 10;

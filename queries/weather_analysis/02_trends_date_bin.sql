-- ============================================================================
-- 02_trends_date_bin.sql: Xu hướng theo khung thời gian bằng date_bin() (P6)
-- Database: weather | Table: weather_hourly
-- Quy ước: dữ liệu lưu ở UTC; "time + INTERVAL '7 hours'" đổi sang giờ Việt Nam (UTC+7,
-- không có giờ mùa hè) để ngày/tuần/tháng cắt đúng nửa đêm địa phương.
-- Origin '2024-01-01T00:00:00Z' là thứ Hai, nên khung 7 ngày bắt đầu từ thứ Hai.
-- Chạy: python python/run_sql.py queries/weather_analysis/02_trends_date_bin.sql
-- ============================================================================

-- Query 1: Theo NGÀY — Hà Nội tháng 09/2024 (bão Yagi đổ bộ 07/09)
SELECT
    date_bin(INTERVAL '1 day', time + INTERVAL '7 hours', TIMESTAMP '2024-01-01T00:00:00Z') AS day_local,
    round(min(temperature_c), 1) AS min_c,
    round(avg(temperature_c), 1) AS avg_c,
    round(max(temperature_c), 1) AS max_c,
    round(min(pressure_msl_hpa), 1) AS min_hpa,
    round(max(wind_gusts_ms), 1) AS max_gust_ms,
    round(sum(precipitation_mm), 1) AS rain_mm
FROM weather_hourly
WHERE location = 'hanoi'
  AND time >= TIMESTAMP '2024-08-31T17:00:00Z'      -- 2024-09-01 00:00 giờ VN
  AND time <  TIMESTAMP '2024-09-30T17:00:00Z'      -- 2024-10-01 00:00 giờ VN
GROUP BY day_local
ORDER BY day_local;

-- Query 2: Theo TUẦN — TP.HCM quý 2/2024 (mùa nóng, giai đoạn nắng nóng tháng 4-5)
SELECT
    date_bin(INTERVAL '7 days', time + INTERVAL '7 hours', TIMESTAMP '2024-01-01T00:00:00Z') AS week_start_local,
    round(avg(temperature_c), 2) AS avg_c,
    round(max(temperature_c), 1) AS max_c,
    round(avg(humidity_pct), 1) AS avg_rh,
    round(sum(precipitation_mm), 1) AS rain_mm
FROM weather_hourly
WHERE location = 'hcm'
  AND time >= TIMESTAMP '2024-03-31T17:00:00Z'      -- 2024-04-01 00:00 giờ VN
  AND time <  TIMESTAMP '2024-06-30T17:00:00Z'      -- 2024-07-01 00:00 giờ VN
GROUP BY week_start_local
ORDER BY week_start_local;

-- Query 3: Theo THÁNG — cả 3 địa điểm, toàn bộ lịch sử (chu kỳ mùa)
SELECT
    date_bin(INTERVAL '1 month', time + INTERVAL '7 hours', TIMESTAMP '2024-01-01T00:00:00Z') AS month_local,
    location,
    round(avg(temperature_c), 2) AS avg_c,
    round(avg(humidity_pct), 1) AS avg_rh,
    round(avg(pressure_msl_hpa), 1) AS avg_hpa,
    round(sum(precipitation_mm), 0) AS rain_mm
FROM weather_hourly
GROUP BY month_local, location
ORDER BY location, month_local;

-- Query 4: Khí hậu theo THÁNG TRONG NĂM (gộp các năm) — so sánh 3 vùng khí hậu
-- Hà Nội có mùa đông lạnh; TP.HCM nóng quanh năm với mùa khô/mưa; Đà Nẵng ở giữa
SELECT
    date_part('month', time + INTERVAL '7 hours') AS month_of_year,
    round(avg(CASE WHEN location = 'hanoi'  THEN temperature_c END), 1) AS hanoi_avg_c,
    round(avg(CASE WHEN location = 'danang' THEN temperature_c END), 1) AS danang_avg_c,
    round(avg(CASE WHEN location = 'hcm'    THEN temperature_c END), 1) AS hcm_avg_c,
    round(avg(CASE WHEN location = 'hanoi'  THEN pressure_msl_hpa END), 1) AS hanoi_avg_hpa,
    round(avg(CASE WHEN location = 'hcm'    THEN pressure_msl_hpa END), 1) AS hcm_avg_hpa
FROM weather_hourly
GROUP BY month_of_year
ORDER BY month_of_year;

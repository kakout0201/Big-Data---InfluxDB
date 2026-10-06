-- ============================================================================
-- 01_summary_by_location.sql: Thống kê tổng hợp theo địa điểm (P6)
-- Database: weather | Table: weather_hourly | Tag: location (hcm, hanoi, danang)
-- Chạy: python python/run_sql.py queries/weather_analysis/01_summary_by_location.sql
-- ============================================================================

-- Query 1: Độ phủ dữ liệu theo địa điểm (số giờ, khoảng thời gian, nguồn)
SELECT
    location,
    count(*) AS hours,
    min(time) AS first_hour_utc,
    max(time) AS last_hour_utc,
    sum(CASE WHEN data_source = 'archive' THEN 1 ELSE 0 END) AS archive_hours,
    sum(CASE WHEN data_source = 'forecast' THEN 1 ELSE 0 END) AS forecast_hours
FROM weather_hourly
GROUP BY location
ORDER BY location;

-- Query 2: Nhiệt độ (°C) — min, max, avg, median, độ lệch chuẩn, phân vị 5% / 95%
SELECT
    location,
    min(temperature_c) AS min_c,
    approx_percentile_cont(temperature_c, 0.05) AS p05_c,
    median(temperature_c) AS median_c,
    avg(temperature_c) AS avg_c,
    approx_percentile_cont(temperature_c, 0.95) AS p95_c,
    max(temperature_c) AS max_c,
    stddev(temperature_c) AS stddev_c
FROM weather_hourly
GROUP BY location
ORDER BY location;

-- Query 3: Độ ẩm tương đối (%) và điểm sương (°C)
SELECT
    location,
    min(humidity_pct) AS min_rh,
    median(humidity_pct) AS median_rh,
    avg(humidity_pct) AS avg_rh,
    max(humidity_pct) AS max_rh,
    min(dew_point_c) AS min_dew_c,
    median(dew_point_c) AS median_dew_c,
    max(dew_point_c) AS max_dew_c
FROM weather_hourly
GROUP BY location
ORDER BY location;

-- Query 4: Áp suất mực nước biển (hPa) — biến quan trọng nhất để nhận diện bão
SELECT
    location,
    min(pressure_msl_hpa) AS min_hpa,
    approx_percentile_cont(pressure_msl_hpa, 0.01) AS p01_hpa,
    median(pressure_msl_hpa) AS median_hpa,
    avg(pressure_msl_hpa) AS avg_hpa,
    max(pressure_msl_hpa) AS max_hpa,
    stddev(pressure_msl_hpa) AS stddev_hpa
FROM weather_hourly
GROUP BY location
ORDER BY location;

-- Query 5: Gió (m/s) — tốc độ trung bình 10 m và gió giật
SELECT
    location,
    median(wind_speed_ms) AS median_wind,
    avg(wind_speed_ms) AS avg_wind,
    approx_percentile_cont(wind_speed_ms, 0.99) AS p99_wind,
    max(wind_speed_ms) AS max_wind,
    median(wind_gusts_ms) AS median_gust,
    approx_percentile_cont(wind_gusts_ms, 0.99) AS p99_gust,
    max(wind_gusts_ms) AS max_gust
FROM weather_hourly
GROUP BY location
ORDER BY location;

-- Query 6: Lượng mưa (mm/giờ) — phân phối lệch, đa số giờ = 0 (zero-inflated)
-- wet_hour = giờ có mưa >= 0.1 mm; median_wet_mm chỉ tính trên các giờ có mưa
SELECT
    location,
    count(*) AS hours,
    sum(CASE WHEN precipitation_mm >= 0.1 THEN 1 ELSE 0 END) AS wet_hours,
    round(100.0 * sum(CASE WHEN precipitation_mm >= 0.1 THEN 1 ELSE 0 END) / count(*), 1) AS wet_pct,
    median(CASE WHEN precipitation_mm >= 0.1 THEN precipitation_mm END) AS median_wet_mm,
    approx_percentile_cont(CASE WHEN precipitation_mm >= 0.1 THEN precipitation_mm END, 0.99) AS p99_wet_mm,
    max(precipitation_mm) AS max_mm_per_hour,
    round(sum(precipitation_mm), 0) AS total_mm
FROM weather_hourly
GROUP BY location
ORDER BY location;

-- Query 7: Tổng lượng mưa theo năm (giờ địa phương UTC+7); năm 2026 chưa đủ 12 tháng
SELECT
    location,
    date_part('year', time + INTERVAL '7 hours') AS year_local,
    count(*) AS hours,
    round(sum(precipitation_mm), 0) AS total_mm,
    max(precipitation_mm) AS max_mm_per_hour
FROM weather_hourly
GROUP BY location, year_local
ORDER BY location, year_local;

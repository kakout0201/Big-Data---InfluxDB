-- ============================================================================
-- 04_diurnal_cycle_hcm.sql: Chu kỳ nhiệt độ ngày - đêm tại TP.HCM (P6)
-- Database: weather | Table: weather_hourly | location = 'hcm'
-- Giờ địa phương = UTC + 7. Mùa khô TP.HCM: tháng 12 - 4; mùa mưa: tháng 5 - 11.
-- Ý nghĩa cho P7: nhiệt độ có chu kỳ ngày-đêm mạnh, nên baseline toàn cục (Z-score
-- trên cả chuỗi) sẽ gắn cờ nhầm theo giờ trong ngày; cần baseline theo giờ hoặc rolling.
-- Chạy: python python/run_sql.py queries/weather_analysis/04_diurnal_cycle_hcm.sql
-- ============================================================================

-- Query 1: Nhiệt độ trung bình theo giờ địa phương (0-23), toàn bộ lịch sử
SELECT
    date_part('hour', time + INTERVAL '7 hours') AS hour_local,
    round(avg(temperature_c), 2) AS avg_c,
    round(min(temperature_c), 1) AS min_c,
    round(max(temperature_c), 1) AS max_c,
    round(stddev(temperature_c), 2) AS stddev_c,
    round(avg(humidity_pct), 1) AS avg_rh
FROM weather_hourly
WHERE location = 'hcm'
GROUP BY hour_local
ORDER BY hour_local;

-- Query 2: Chu kỳ ngày-đêm theo mùa — mùa khô (12-4) vs mùa mưa (5-11)
SELECT
    date_part('hour', time + INTERVAL '7 hours') AS hour_local,
    round(avg(CASE WHEN date_part('month', time + INTERVAL '7 hours') IN (12, 1, 2, 3, 4)
                   THEN temperature_c END), 2) AS dry_season_avg_c,
    round(avg(CASE WHEN date_part('month', time + INTERVAL '7 hours') BETWEEN 5 AND 11
                   THEN temperature_c END), 2) AS rainy_season_avg_c,
    round(avg(CASE WHEN date_part('month', time + INTERVAL '7 hours') BETWEEN 5 AND 11
                   THEN precipitation_mm END), 3) AS rainy_season_avg_rain_mm
FROM weather_hourly
WHERE location = 'hcm'
GROUP BY hour_local
ORDER BY hour_local;

-- Query 3: Biên độ nhiệt ngày (max - min trong ngày địa phương), trung bình theo tháng trong năm
SELECT
    date_part('month', day_local) AS month_of_year,
    count(*) AS days,
    round(avg(daily_min_c), 2) AS avg_daily_min_c,
    round(avg(daily_max_c), 2) AS avg_daily_max_c,
    round(avg(daily_max_c - daily_min_c), 2) AS avg_amplitude_c,
    round(max(daily_max_c - daily_min_c), 1) AS max_amplitude_c
FROM (
    SELECT
        date_bin(INTERVAL '1 day', time + INTERVAL '7 hours', TIMESTAMP '2024-01-01T00:00:00Z') AS day_local,
        min(temperature_c) AS daily_min_c,
        max(temperature_c) AS daily_max_c,
        count(*) AS hours
    FROM weather_hourly
    WHERE location = 'hcm'
    GROUP BY day_local
) AS daily
WHERE hours = 24                       -- chỉ tính ngày đủ 24 giờ
GROUP BY month_of_year
ORDER BY month_of_year;

-- Query 4: Giờ đạt nhiệt độ cao nhất trong ngày — phân bố (giờ nào thường nóng nhất)
SELECT
    date_part('hour', time + INTERVAL '7 hours') AS hour_of_daily_max,
    count(*) AS days
FROM (
    SELECT
        time,
        row_number() OVER (
            PARTITION BY date_bin(INTERVAL '1 day', time + INTERVAL '7 hours', TIMESTAMP '2024-01-01T00:00:00Z')
            ORDER BY temperature_c DESC, time ASC
        ) AS rank_in_day
    FROM weather_hourly
    WHERE location = 'hcm'
) AS ranked
WHERE rank_in_day = 1
GROUP BY hour_of_daily_max
ORDER BY days DESC
LIMIT 6;

# SQL phân tích dữ liệu thời tiết (P6)

Các câu truy vấn SQL (dialect Apache DataFusion) trên bảng `weather.weather_hourly`.

Dữ liệu được lưu theo **UTC**. Mọi phép gom theo ngày, tuần hay tháng đều đổi sang giờ Việt Nam bằng `time + INTERVAL '7 hours'` (UTC+7, không có giờ mùa hè). Nhờ vậy, một "ngày" được cắt đúng tại nửa đêm giờ địa phương.

| File | Nội dung |
|---|---|
| `01_summary_by_location.sql` | Độ phủ dữ liệu; min / max / avg / median / phân vị của nhiệt độ, độ ẩm, áp suất, gió, mưa theo từng địa điểm |
| `02_trends_date_bin.sql` | `date_bin()` theo ngày (Hà Nội 09/2024), theo tuần (TP.HCM quý 2/2024), theo tháng (toàn bộ lịch sử); khí hậu theo tháng trong năm |
| `03_yagi_hanoi.sql` | Bão Yagi: chuỗi theo giờ (biến thiên áp suất 3 giờ, mưa cộng dồn), thời điểm cực trị, so sánh với tháng tham chiếu, tương quan Pearson |
| `04_diurnal_cycle_hcm.sql` | Chu kỳ ngày – đêm ở TP.HCM theo giờ địa phương và theo mùa; biên độ nhiệt ngày; giờ nóng nhất trong ngày |
| `05_heatwave_hcm_2024.sql` | Nắng nóng TP.HCM tháng 04–05/2024: nhiệt độ cao nhất từng ngày, so sánh giữa các năm, các giờ nóng nhất |

Chạy từng file (mỗi câu lệnh được in thành một bảng có tiêu đề):

```bash
python python/run_sql.py queries/weather_analysis/03_yagi_hanoi.sql --max-rows 80
```

Có thể chạy một câu đơn lẻ bằng CLI trong container:

```bash
docker exec influxdb3-core influxdb3 query --host https://127.0.0.1:8181 --tls-no-verify -d weather "SELECT ..."
```

Truy vấn quét toàn bộ lịch sử mất khoảng 1,5–5 giây, vì dữ liệu nạp bù nằm rải trên khoảng 24.000 file Parquet (xem `CLAUDE.md`). Truy vấn có lọc theo khoảng thời gian chỉ mất dưới 0,3 giây.

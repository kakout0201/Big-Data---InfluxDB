# Grafana — Dashboard thời tiết & bất thường

Grafana 11.5.2 đọc trực tiếp **InfluxDB 3 Core** bằng SQL (giao thức Flight SQL), dùng datasource `influxdb` có sẵn, không cần plugin ngoài. Mọi cấu hình được provisioning từ file trong thư mục này.

```text
InfluxDB 3 Core (database weather)
  ├── weather_hourly      dữ liệu theo giờ (Open-Meteo)
  └── weather_anomalies   kết quả phát hiện bất thường (python/anomaly_job.py)
        │  Flight SQL qua HTTPS :8181 (mạng nội bộ Docker, CA trong certs/ca-bundle.crt)
        ▼
Grafana :3000  ──  dashboard "Thời tiết & Bất thường — InfluxDB 3" (uid weather_analytics)
```

## Truy cập

- http://localhost:3000/d/weather_analytics
- Đăng nhập bằng `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` trong `.env`. Truy cập ẩn danh bị tắt.

## Provisioning

| File | Nội dung |
|---|---|
| `provisioning/datasources/influxdb3.yml` | Datasource `InfluxDB 3 Weather` (uid `influxdb3_weather`, default), `version: SQL`, `dbName: ${WEATHER_INFLUXDB_DATABASE}`, token lấy từ `${INFLUXDB_TOKEN}`. `deleteDatasources` gỡ datasource legacy của Phase 1. |
| `provisioning/dashboards/dashboards.yml` | Provider "Weather": nạp mọi JSON trong `dashboards_json/`, quét lại mỗi 5 giây. |
| `dashboards_json/weather_analytics.json` | Dashboard chính. |

- Sửa dashboard bằng cách sửa JSON; Grafana tự nạp lại sau khoảng 5 giây. Thay đổi lưu trên giao diện sẽ bị file ghi đè.
- Đổi biến môi trường hoặc datasource thì phải tạo lại container bằng `docker compose up -d grafana`; `restart` không nạp env mới.

## Bố cục dashboard

**Biến:**
- `Địa điểm` (`$location`): TP.HCM (mặc định), Hà Nội, Đà Nẵng.
- `Gom nhóm` (`$time_bin`): auto, 1h, 6h, 1d. Auto chọn khoảng 200 điểm, tối thiểu 1h.
- `Biến (bảng nhật ký)` (`$field`): chỉ lọc bảng nhật ký.

**Liên kết nhanh** (thanh tiêu đề):
- Siêu bão Yagi: Hà Nội, 06–09/09/2024.
- Nắng nóng TP.HCM: 04/2024.
- 7 ngày gần nhất.

Grafana 11.5.2 không cho đặt preset có tên trong bộ chọn thời gian, nên các preset được làm bằng link có sẵn `from`/`to`/`var-location`.

| Hàng | Panel | Ghi chú |
|---|---|---|
| Tổng quan tức thời | Nhiệt độ, Độ ẩm, Khí áp, Gió giật, Tổng mưa 24h | Stat: giá trị cuối của khung, sparkline. Mưa 24h là tổng trượt 24 giờ. |
| | Cờ bất thường | Tổng số cờ (phương pháp × giờ) trong khung. |
| | Gauge nhiệt độ | Xanh dương < 15 °C, xanh lá, vàng ≥ 35, cam ≥ 37, đỏ ≥ 39 °C (ngưỡng nắng nóng). |
| | Gauge gió giật | Thang Beaufort: vàng cấp 6 (10,8 m/s), cam cấp 8 (17,2), đỏ cấp 10 (24,5). |
| | Số giờ bị gắn cờ theo nhóm | Bar gauge. |
| Diễn biến chuỗi thời gian | Nhiệt độ & điểm sương | Đường cong mượt, đường đứt nét 35 °C. |
| | Khí áp & lượng mưa | Khí áp ở trục trái (đường), mưa ở trục phải (cột). |
| Phát hiện bất thường | Dòng thời gian bất thường | State Timeline gồm 5 dải (nắng nóng kéo dài, áp suất thấp, gió giật, mưa 24h, dữ liệu kẹt). Mức 0–3: xám, vàng, cam, đỏ. |
| | Khí áp / Gió giật với điểm bất thường | Chấm đỏ tại giờ bị gắn cờ. Chấm xám là trung bình khí hậu (với khí áp). |
| Nhật ký bất thường | Bảng `weather_anomalies` | Mới nhất trước. Cột Mức độ là badge màu: đỏ (cấp ≥ 10, rất mạnh, rất to), cam (cấp 8–9, mạnh, gay gắt), vàng (nắng nóng, mưa to, vừa), tím (giá trị kẹt). |

## Quy ước truy vấn

- Mọi truy vấn có `time >= $__timeFrom() AND time <= $__timeTo() AND location = '$location'`.
- Gom nhóm bằng `date_bin(INTERVAL '$time_bin', time, TIMESTAMP '1970-01-01T17:00:00Z')`. Origin 17:00 UTC là 0h giờ VN.
- Gauge chỉ đọc 24 giờ cuối của khung. State Timeline sinh trục thời gian bằng `generate_series`, nên chỉ đọc bảng bất thường.
- Không dùng comment `--` trong SQL: câu lệnh được gộp thành một dòng.

Kiểm tra sau mỗi lần sửa:

```bash
python python/test_check_dashboard.py        # quy tắc tĩnh trên JSON (không cần Grafana)
python python/check_dashboard.py             # health datasource + chạy 18 truy vấn x 6 kịch bản qua /api/ds/query
```

## Hiệu năng

Đo qua `/api/ds/query` ngày 2026-10-06:

| Khung thời gian | Truy vấn đọc `weather_hourly` |
|---|---|
| 7 ngày | trung vị khoảng 90 ms |
| 30 ngày | khoảng 140 ms |
| 1 năm | khoảng 1,5 s |

Bản Core không có compaction, nên mỗi giờ lịch sử là một file Parquet. Chi phí truy vấn tăng theo số file bị chạm tới chứ không theo số điểm trả về, vì vậy gom nhóm không làm truy vấn khung dài nhanh hơn. Xem thêm `CLAUDE.md`, mục InfluxDB Conventions.

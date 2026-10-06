# Hệ thống lưu trữ, phân tích và phát hiện bất thường dữ liệu thời tiết chuỗi thời gian sử dụng InfluxDB 3

Đồ án môn **Big Data**.

> **Trạng thái:** đang phát triển. Pipeline thu thập → làm sạch → InfluxDB → phát hiện bất thường → Grafana đã chạy đầy đủ; còn lại kiểm thử/đánh giá và báo cáo (xem roadmap ở cuối tài liệu).

---

## 1. Project

Hệ thống thu thập dữ liệu thời tiết dạng chuỗi thời gian, làm sạch và lưu vào **InfluxDB 3 Core**, phân tích bằng SQL, **phát hiện bất thường** bằng các phương pháp thống kê giải thích được, và trực quan hóa trên **Grafana**.

Repository được phát triển tiếp từ tiểu luận về InfluxDB 3 (demo giám sát server và benchmark). Toàn bộ trạng thái của tiểu luận được lưu ở git tag `phase1-essay`; tài liệu benchmark và kịch bản demo nằm trong `archive/phase1-essay/`.

## 2. Architecture

```text
Weather Data Source
        ↓
Data Collection          (Python)
        ↓
Data Cleaning / Transformation
        ↓
InfluxDB 3 Core          (Line Protocol qua HTTPS :8181)
        ↓
SQL / Analysis           (Apache DataFusion SQL)
        ↓
Anomaly Detection
        ↓
Grafana Dashboard        (:3000, Flight SQL)
```

## 3. Technology Stack

| Thành phần | Công nghệ |
|---|---|
| Database | InfluxDB 3 Core (Apache Arrow, DataFusion, Parquet) |
| Xử lý dữ liệu | Python 3.11 (`influxdb3-python`, `python-dotenv`) |
| Truy vấn | SQL (dialect DataFusion) |
| Trực quan hóa | Grafana 11.5 |
| Triển khai | Docker Compose |

## 4. How to run

### Yêu cầu
- Docker Engine và Docker Compose v2; cổng `8181` và `3000` còn trống.
- Python 3.11.
- Chứng chỉ TLS trong `certs/` (không commit lên git): `cert.pem`, `key.pem` (self-signed, SAN gồm `influxdb`, `influxdb3-core`, `localhost`, `127.0.0.1`) và `ca-bundle.crt` (CA bundle mà Grafana dùng để tin chứng chỉ trên).

### Các bước
```bash
# 1. Cấu hình biến môi trường
cp .env.example .env        # rồi điền INFLUXDB_TOKEN và GRAFANA_ADMIN_PASSWORD

# 2. Khởi động InfluxDB 3 + Grafana
docker compose up -d
docker compose ps

# 3. Môi trường Python
python -m venv .venv
.venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install influxdb3-python python-dotenv
```

`INFLUXDB_URL` phải là `https://localhost:8181` vì InfluxDB chạy TLS.

### Nạp dữ liệu thời tiết
```bash
# Dữ liệu lịch sử từ 2024-01-01 tới hôm qua (Archive API), khoảng 1 phút
python python/weather_collector.py backfill --start 2024-01-01

# Các giờ gần nhất (Forecast API); thêm --interval-minutes 60 để chạy liên tục
python python/weather_collector.py recent --past-days 7

# Kiểm tra dữ liệu đã lưu (chỉ đọc)
python python/weather_collector.py verify

# Unit test cho bước làm sạch (không cần mạng hay database)
python python/test_weather_cleaning.py
```

## 5. Data pipeline

| Bước | Trạng thái |
|---|---|
| Nguồn dữ liệu | **Open-Meteo** (CC BY 4.0, không cần API key): Archive API cho dữ liệu lịch sử, Forecast API cho các giờ gần nhất |
| Địa điểm | TP.HCM (`hcm`), Hà Nội (`hanoi`), Đà Nẵng (`danang`), dữ liệu theo giờ từ 2024-01-01 |
| Thu thập | `python/weather_collector.py`: nạp theo chunk, ghi batch, tự kiểm tra `count(*)` sau khi ghi |
| Làm sạch | `python/weather_cleaning.py`: chuẩn hóa thời gian UTC, kiểm tra đơn vị, ép kiểu, loại giá trị không thể xảy ra về mặt vật lý (giữ lại giá trị cực đoan thật), khử trùng, báo cáo số liệu từng bước |
| Ghi vào InfluxDB | Database `weather`, bảng `weather_hourly`; dữ liệu archive ghi đè dữ liệu forecast của cùng giờ |

Nguồn dữ liệu: *Weather data by [Open-Meteo.com](https://open-meteo.com/)* (CC BY 4.0).

## 6. InfluxDB

- Một service InfluxDB 3 Core (`influxdb:3-core`), container `influxdb3-core`, dữ liệu lưu trong Docker volume `influxdb3_data`, bật TLS và xác thực bằng token.
- Schema dữ liệu thời tiết:

  | Thành phần | Giá trị |
  |---|---|
  | Database / bảng | `weather` / `weather_hourly` |
  | Tag | `location` (`hcm`, `hanoi`, `danang`) |
  | Timestamp | đầu mỗi giờ, UTC |
  | Field (float) | `temperature_c`, `humidity_pct`, `dew_point_c`, `precipitation_mm`, `pressure_msl_hpa`, `cloud_cover_pct`, `wind_speed_ms`, `wind_direction_deg`, `wind_gusts_ms` |
  | Field khác | `weather_code` (integer, mã WMO), `data_source` (string: `forecast` / `archive`) |
- Truy vấn thủ công:
  ```bash
  docker exec influxdb3-core influxdb3 query --database <DATABASE> --token <TOKEN> "SELECT ..."
  ```

## 7. Anomaly Detection

Chức năng trọng tâm của đồ án. Chỉ dùng các phương pháp thống kê giải thích được, không dùng ML (`python/weather_anomaly.py`). Mỗi điểm bị gắn cờ đều kèm câu giải thích, ví dụ: *"982.0 hPa lệch -8.5σ so với TB cùng tháng, cùng giờ các năm khác (1008.9 hPa)"*.

Các phương pháp đã được so sánh trên hai sự kiện thật (bão Yagi ở Hà Nội 09/2024, nắng nóng ở TP.HCM 04/2024) và trên bất thường giả có đáp án (`python/evaluate_anomaly.py`). Phương pháp được chọn cho từng biến:

| Biến | Phương pháp | Lý do |
|---|---|---|
| Áp suất | Z-score khí hậu (cùng tháng và giờ của các năm khác), k = 3 | Phát hiện Yagi sớm 24 giờ, 0,7 báo động giả/năm |
| Gió giật | IQR theo tháng, cộng ngưỡng cấp 8 (17,2 m/s) | Ít báo động giả; mức nghiêm trọng gắn theo cấp Beaufort |
| Mưa 24h | IQR trên các khoảng có mưa, cộng ngưỡng 50 mm | Phù hợp với phân phối có rất nhiều giá trị 0 |
| Nhiệt độ | Trung bình 168 giờ của Z-score khí hậu ≥ 1,0 | Bắt được nắng nóng kéo dài (18/30 ngày), điều mà các phương pháp xét từng giờ bỏ sót |
| Chất lượng dữ liệu | Phát hiện giá trị đứng yên ≥ 6 giờ | Bắt được 100% đoạn bị kẹt giả lập |

Kết quả được lưu vào bảng `weather_anomalies`:

```bash
python python/anomaly_job.py --dry-run   # xem trước
python python/anomaly_job.py             # xóa rồi ghi lại bảng, đối chiếu count(*)
```

## 8. Grafana

- Truy cập: http://localhost:3000, đăng nhập bằng `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` trong `.env`.
- Datasource `InfluxDB 3 Weather` (database `weather`, SQL qua Flight SQL) và dashboard được provisioning tự động từ `grafana/provisioning/` và `grafana/dashboards_json/`.
- Dashboard **Thời tiết & Bất thường**: http://localhost:3000/d/weather_analytics. Bố cục 4 hàng:
  1. **Tổng quan tức thời:** giá trị mới nhất kèm sparkline, gauge nhiệt độ và gió giật theo thang khí tượng, số cờ bất thường.
  2. **Diễn biến chuỗi thời gian:** nhiệt độ và điểm sương; khí áp và lượng mưa trên hai trục.
  3. **Phát hiện bất thường:** dòng thời gian bất thường theo nhóm hiện tượng; khí áp và gió giật có chấm đỏ tại giờ bị gắn cờ.
  4. **Nhật ký bất thường:** bảng kèm mức độ và câu giải thích.
- Chọn địa điểm bằng biến `Địa điểm`. Liên kết nhanh trên thanh tiêu đề mở đúng sự kiện: bão Yagi (Hà Nội, 06–09/09/2024), nắng nóng TP.HCM (04/2024), 7 ngày gần nhất.
- Trước khi demo, cập nhật dữ liệu và bất thường:
  ```bash
  python python/weather_collector.py recent --past-days 7
  python python/anomaly_job.py
  python python/check_dashboard.py      # chạy mọi truy vấn của dashboard qua Grafana
  ```
- Chi tiết: `grafana/README.md`.

## 9. Development

```text
python/          Pipeline weather, phát hiện bất thường, kiểm tra dashboard + unit test (xem python/README.md)
queries/         SQL phân tích dữ liệu thời tiết (queries/weather_analysis/)
grafana/         Provisioning datasource + dashboard weather_analytics.json
archive/         Tài liệu và code của tiểu luận (đóng băng, không bảo trì)
CLAUDE.md        Hướng dẫn chi tiết cho việc phát triển với Claude Code
```

### Roadmap

| Giai đoạn | Nội dung | Trạng thái |
|---|---|---|
| P1 | Dọn dẹp repository | Hoàn thành |
| P2 | Chọn và khảo sát nguồn dữ liệu thời tiết | Hoàn thành |
| P3 | Thu thập dữ liệu | Hoàn thành |
| P4 | Làm sạch dữ liệu | Hoàn thành |
| P5 | Schema InfluxDB cho dữ liệu thời tiết | Hoàn thành |
| P6 | Truy vấn và phân tích | Hoàn thành |
| P7 | Phát hiện bất thường | Hoàn thành |
| P8 | Grafana dashboard | Hoàn thành |
| P9 | Kiểm thử và đánh giá | Tiếp theo |
| P10 | Demo và báo cáo | |

### Bảo mật
Không commit `.env`, token, mật khẩu hay private key. `.env.example` chỉ chứa placeholder.

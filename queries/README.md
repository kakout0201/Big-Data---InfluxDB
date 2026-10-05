# InfluxDB 3 SQL Analytics Collection

> **Legacy (Phase 1 – tiểu luận):** tài liệu này mô tả demo giám sát server (`server_monitoring.server_metrics`). Nó sẽ được thay thế khi phần dữ liệu thời tiết được xây dựng — xem `CLAUDE.md` ở root.

## 1. Purpose (Mục đích)

Thư mục này chứa tập hợp các câu truy vấn **SQL tiêu chuẩn (Apache DataFusion SQL dialect)** phục vụ khai thác, thống kê và giám sát dữ liệu chuỗi thời gian được lưu trữ trong **InfluxDB 3 Core**.

---

## 2. Database & Table

* **Database:** `server_monitoring`
* **Table:** `server_metrics`
* **Dimensions (Tags):** `host`, `region`
* **Metrics (Fields):** `cpu_usage`, `memory_usage`, `network_in`, `network_out`, `error_rate`
* **Time Column:** `time` (`Timestamp(ns)`)

---

## 3. Phân loại Bộ Query

### A. [01_basic.sql](01_basic.sql) — Truy vấn Cơ bản & Khám phá Schema
* **Query 1:** Đếm tổng số bản ghi trong bảng (`COUNT(*)`).
* **Query 2:** Lấy 10 bản ghi gần nhất với đầy đủ các trường metrics (`ORDER BY time DESC LIMIT 10`).
* **Query 3:** Liệt kê danh sách các máy chủ (`DISTINCT host`).
* **Query 4:** Liệt kê danh sách các khu vực triển khai (`DISTINCT region`).

### B. [02_aggregation.sql](02_aggregation.sql) — Thống kê & Tổng hợp (Aggregations)
* **Query 5:** Tính CPU trung bình toàn hệ thống (`AVG(cpu_usage)`).
* **Query 6:** Tính CPU trung bình theo từng máy chủ (`GROUP BY host ORDER BY avg_cpu DESC`).
* **Query 7:** Tính dung lượng RAM trung bình theo từng khu vực (`GROUP BY region`).
* **Query 8:** Tìm mức CPU cao nhất từng máy chủ từng ghi nhận (`MAX(cpu_usage)`).
* **Query 9:** Thống kê tỷ lệ lỗi trung bình theo khu vực (`AVG(error_rate)`).
* **Query 10:** Lọc Top 5 máy chủ có tải CPU cao nhất (`LIMIT 5`).

### C. [03_time_series.sql](03_time_series.sql) — Phân tích Chuỗi thời gian & Cảnh báo (Time-Series)
* **Query 11:** Biểu đồ xu hướng CPU theo thời gian của từng máy chủ.
* **Query 12:** Biểu đồ xu hướng Memory theo thời gian của từng máy chủ.
* **Query 13:** Phân khoảng thời gian (Time Window Bucketing) tính CPU trung bình theo cửa sổ 5 giây sử dụng hàm `date_bin(INTERVAL '5 seconds', time, TIMESTAMP '1970-01-01 00:00:00Z')`.
* **Query 14:** Phát hiện cảnh báo quá tải CPU (`WHERE cpu_usage > 80.0`).
* **Query 15:** Phát hiện cảnh báo nghẽn bộ nhớ RAM (`WHERE memory_usage > 80.0`).

---

## 4. Hướng dẫn Thực thi Truy vấn

### Cách 1: Sử dụng InfluxDB 3 CLI bên trong Docker Container
```bash
# Cú pháp tổng quát
docker exec influxdb3-core influxdb3 query \
  --database server_monitoring \
  --token <YOUR_INFLUXDB_TOKEN> \
  "SELECT count(*) FROM server_metrics"

# Chạy trực tiếp từ file .sql
docker exec -i influxdb3-core influxdb3 query \
  --database server_monitoring \
  --token <YOUR_INFLUXDB_TOKEN> \
  -f /dev/stdin < queries/01_basic.sql
```

### Cách 2: Sử dụng Python InfluxDB 3 Client (`influxdb_client_3`)
```python
from influxdb_client_3 import InfluxDBClient3
from config import InfluxDBConfig

cfg = InfluxDBConfig.load()
client = InfluxDBClient3(host=cfg.url, token=cfg.token, database=cfg.database)

table = client.query("SELECT host, avg(cpu_usage) as avg_cpu FROM server_metrics GROUP BY host")
print(table.to_pandas())
```

---

## 5. Ứng dụng cho các Task tiếp theo

* **Sử dụng cho Grafana Dashboard (Phase 8):**
  * `Query 6, 7, 9` làm các widget bảng/Gauge tóm tắt (Stat & Bar Gauge).
  * `Query 11, 12, 13` làm Time Series Line Charts thời gian thực.
  * `Query 14, 15` làm Alerting Rules và bảng sự cố bất thường (Incident Log).
* **Sử dụng cho Benchmark Query Latency (Phase 7):**
  * Đánh giá thời gian phản hồi (P50, P95, P99 latency) giữa Point Query (`Query 2`), Aggregate Scan (`Query 5, 6`), và Windowed GroupBy (`Query 13`).

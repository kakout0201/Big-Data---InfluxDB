# Grafana Module — InfluxDB 3 Real-Time Monitoring Dashboard

> **Legacy (Phase 1 – tiểu luận):** tài liệu này mô tả demo giám sát server (`server_monitoring.server_metrics`). Nó sẽ được thay thế khi phần dữ liệu thời tiết được xây dựng — xem `CLAUDE.md` ở root.

Tài liệu hướng dẫn triển khai, cấu hình và sử dụng Grafana Dashboard phục vụ giám sát hạ tầng thời gian thực với **InfluxDB 3 Core** cho đề tài Big Data.

---

## 1. Kiến trúc Tích hợp (Architecture)

```text
+-------------------------+
|  Python Data Generator  |
|  (10 nodes, 3 regions)  |
+------------+------------+
             |
             | Line Protocol (HTTPS)
             v
+-------------------------+
|     InfluxDB 3 Core     |
|   (Database Engine)     |
|  [server_monitoring]    |
+------------+------------+
             |
             | Apache Arrow Flight SQL (gRPC / Port 8181)
             v
+-------------------------+
|      Grafana 11.5       |
| (Native InfluxDB SQL)   |
|   [Port 3000 Web UI]    |
+-------------------------+
```

---

## 2. Truy cập Grafana Web UI

- **URL:** [http://localhost:3000](http://localhost:3000)
- **Bảo mật & Xác thực:** Đã tắt hoàn toàn Anonymous access, bắt buộc đăng nhập (Authentication required).
- **Tài khoản đăng nhập:** Sử dụng thông tin quản trị viên được cấu hình bảo mật trong file `.env` (`GRAFANA_ADMIN_USER` và `GRAFANA_ADMIN_PASSWORD`).
- **Dashboard trực tiếp:** `http://localhost:3000/d/server_monitoring_influxdb3/server-monitoring-e28094-influxdb-3`

---

## 3. Cấu hình Datasource Provisioning

Datasource được tự động nạp khi khởi động container thông qua file:
`grafana/provisioning/datasources/influxdb3.yml`

* **Name:** `InfluxDB 3 Core`
* **Type:** `influxdb` (Phiên bản: `SQL`)
* **UID:** `influxdb3_datasource`
* **URL:** `https://influxdb:8181` (kết nối nội bộ Docker network)
* **Database:** `server_monitoring`
* **Authentication:** Bearer Token (`${INFLUXDB_TOKEN}`)
* **Giao thức backend:** Apache Arrow Flight SQL over gRPC

---

## 4. Cấu trúc Dashboard (12 Panels)

Dashboard `Server Monitoring — InfluxDB 3` được chia làm 4 hàng (Row) logic:

### Hàng 1: System Overview & Key Metrics (Tổng quan hệ thống)
1. **Total Records** (`stat`): Tổng số bản ghi đo đạc telemetry trong bảng `server_metrics`.
   ```sql
   SELECT count(*) AS total_records FROM server_metrics
   ```
2. **Average CPU Usage** (`gauge`): Mức sử dụng CPU trung bình toàn hệ thống (0–100%, ngưỡng cảnh báo 60% vàng, 80% đỏ).
   ```sql
   SELECT avg(cpu_usage) AS avg_cpu FROM server_metrics
   ```
3. **Average Memory Usage** (`gauge`): Mức sử dụng RAM trung bình (0–100%, ngưỡng cảnh báo 70% vàng, 85% đỏ).
   ```sql
   SELECT avg(memory_usage) AS avg_memory FROM server_metrics
   ```
4. **Average Error Rate** (`stat`): Tỷ lệ lỗi trung bình (%) (ngưỡng 2.0% vàng, 5.0% đỏ).
   ```sql
   SELECT avg(error_rate) AS avg_error_rate FROM server_metrics
   ```

### Hàng 2: Real-Time Telemetry Trends (Chuỗi thời gian thời gian thực)
5. **CPU Usage Over Time** (`timeseries`): Biểu đồ đường mịn biểu diễn mức CPU theo từng máy chủ (`host`), hỗ trợ phân tách đa chuỗi (`partitionByValues`).
   ```sql
   SELECT time, host, cpu_usage FROM server_metrics ORDER BY time ASC
   ```
6. **Memory Usage Over Time** (`timeseries`): Biểu đồ chuỗi thời gian RAM của 10 server.
   ```sql
   SELECT time, host, memory_usage FROM server_metrics ORDER BY time ASC
   ```
7. **Network Traffic (MB/s In / Out)** (`timeseries`): Băng thông mạng truyền nhận (`network_in` xanh lá, `network_out` cam).
   ```sql
   SELECT time, network_in, network_out FROM server_metrics ORDER BY time ASC
   ```

### Hàng 3: Server & Regional Aggregations (Phân tích theo Server và Vùng)
8. **Average CPU by Server** (`barchart`): Xếp hạng tải CPU trung bình giữa các node máy chủ từ cao xuống thấp.
   ```sql
   SELECT host, avg(cpu_usage) AS avg_cpu FROM server_metrics GROUP BY host ORDER BY avg_cpu DESC
   ```
9. **Average Memory by Region** (`barchart`): So sánh tải RAM giữa 3 khu vực (`hcm`, `hanoi`, `danang`).
   ```sql
   SELECT region, avg(memory_usage) AS avg_memory FROM server_metrics GROUP BY region ORDER BY avg_memory DESC
   ```
10. **Error Rate by Region** (`barchart`): Tỷ lệ lỗi theo từng khu vực địa lý.
    ```sql
    SELECT region, avg(error_rate) AS avg_error_rate FROM server_metrics GROUP BY region ORDER BY avg_error_rate DESC
    ```

### Hàng 4: Anomalies & Incident Detection (Phát hiện sự cố bất thường)
11. **High CPU Incidents (> 80%)** (`table`): Danh sách sự kiện bất thường vượt ngưỡng CPU 80%.
    ```sql
    SELECT time, host, region, cpu_usage FROM server_metrics WHERE cpu_usage > 80.0 ORDER BY time DESC
    ```
12. **High Memory Incidents (> 80%)** (`table`): Danh sách sự kiện bất thường vượt ngưỡng RAM 80%.
    ```sql
    SELECT time, host, region, memory_usage FROM server_metrics WHERE memory_usage > 80.0 ORDER BY time DESC
    ```

---

## 5. Dashboard Variables (Bộ lọc tương tác)

Dashboard tích hợp 2 biến tương tác động truy vấn trực tiếp từ InfluxDB 3:
* **`$host`**: Danh sách 10 máy chủ (`server-01` đến `server-10`), hỗ trợ chọn nhiều (Multi-select) hoặc Tất cả (All).
  - Query: `SELECT DISTINCT host FROM server_metrics ORDER BY host`
* **`$region`**: Danh sách 3 khu vực (`danang`, `hanoi`, `hcm`).
  - Query: `SELECT DISTINCT region FROM server_metrics ORDER BY region`

---

## 6. Hướng dẫn chạy Live Demo

Để trình diễn dashboard tự động cập nhật dữ liệu thời gian thực:

1. Mở trình duyệt truy cập Dashboard: [http://localhost:3000](http://localhost:3000)
2. Bật chế độ tự động làm mới: chọn **5s** ở góc trên bên phải dashboard, khoảng thời gian chọn **Last 15 minutes**.
3. Chạy Data Generator trong terminal:
   ```bash
   # Chạy liên tục mỗi 1 giây (nhấn Ctrl+C để dừng khi hoàn tất demo):
   python python/generator.py --interval 1

   # Hoặc chạy thử nghiệm 30 batch:
   python python/generator.py --interval 1 --iterations 30
   ```
4. Quan sát các biểu đồ Time-series, Gauge và Barchart cập nhật trực tiếp theo từng giây.

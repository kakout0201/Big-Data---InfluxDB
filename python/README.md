# Python Module — Time-Series Data Generator

## 1. Purpose (Mục đích)

Module này chịu trách nhiệm mô phỏng và phát sinh dữ liệu chuỗi thời gian (time-series telemetry) cho hệ thống giám sát hạ tầng máy chủ phân tán và ghi trực tiếp vào **InfluxDB 3 Core** theo cơ chế batching.

---

## 2. Data Model (Mô hình Dữ liệu)

* **Database:** `server_monitoring`
* **Table / Measurement:** `server_metrics`

### Tags (Indexed Dimensions)
* `host` (String): Tên định danh máy chủ (`server-01` đến `server-10`).
* `region` (String): Vùng địa lý triển khai (`hcm`, `hanoi`, `danang`).

### Fields (Metrics / Numerical Values)
* `cpu_usage` (Float): Tỷ lệ sử dụng CPU (0.0% – 100.0%).
* `memory_usage` (Float): Tỷ lệ sử dụng bộ nhớ RAM (0.0% – 100.0%).
* `network_in` (Float): Lưu lượng mạng chiều nhận vào (MB/s).
* `network_out` (Float): Lưu lượng mạng chiều gửi đi (MB/s).
* `error_rate` (Float): Tỷ lệ lỗi hệ thống (0.0% – 10.0%).

### Timestamp
* `time`: Thời gian ghi nhận dữ liệu theo chuẩn UTC với độ chính xác nanosecond (`timestamp[ns]`).

---

## 3. Danh sách Server & Region Mapping

Hệ thống quản lý 10 máy chủ phân bố cố định trên 3 khu vực:

| Region | Servers |
| :--- | :--- |
| **hcm** | `server-01`, `server-02`, `server-03`, `server-04` |
| **hanoi** | `server-05`, `server-06`, `server-07` |
| **danang** | `server-08`, `server-09`, `server-10` |

---

## 4. Configuration (Cấu hình)

Mã nguồn nạp cấu hình từ biến môi trường hoặc file `.env` tại thư mục root của dự án:

```env
INFLUXDB_URL=http://localhost:8181
INFLUXDB_DATABASE=server_monitoring
INFLUXDB_TOKEN=your_token_here
```

*(Lưu ý: Không hard-code hoặc commit token bí mật vào repository).*

---

## 5. Usage (Hướng dẫn Sử dụng)

### Cài đặt dependencies (trong virtual environment `.venv`):
```bash
pip install influxdb3-python python-dotenv
```

### Chạy sinh dữ liệu thử nghiệm (Smoke Test / Finite Batch):
```bash
# Sinh dữ liệu mỗi 1 giây trong 10 vòng lặp (100 points)
python python/generator.py --interval 1 --iterations 10

# Chạy với seed để dữ liệu có tính lặp lại (reproducible)
python python/generator.py --interval 1 --iterations 10 --seed 42
```

### Chạy sinh dữ liệu liên tục thời gian thực (Streaming Mode):
```bash
# Chạy vô hạn cho tới khi bấm Ctrl + C
python python/generator.py --interval 1 --iterations 0
```

### Tham số dòng lệnh (CLI Flags):
* `--interval` (float, default: `1.0`): Khoảng thời gian nghỉ giữa các lần ghi batch (giây).
* `--iterations` (int, default: `10`): Số vòng lặp batch cần tạo. Nhập `<= 0` để stream liên tục.
* `--seed` (int, optional): Khởi tạo seed cho hàm ngẫu nhiên phục vụ kiểm thử.

---

## 6. Expected Output

Khi chạy kịch bản `--interval 1 --iterations 10`:
* **Số iteration:** 10
* **Số server mỗi iteration:** 10
* **Tổng số points ghi vào InfluxDB:** `10 × 10 = 100 points`.
* **Logging mẫu:**
  ```text
  [INFO] Connecting to InfluxDB 3 Core (URL: http://localhost:8181)
  [INFO] Target Database: server_monitoring
  [INFO] Servers: 10 across 3 regions (hcm, hanoi, danang)
  [INFO] Batch interval: 1.0s | Iterations: 10
  [INFO] Iteration 1/10 — wrote 10 points (timestamp: 2026-09-02T03:34:01.221229+00:00)
  ...
  [INFO] Data generation completed successfully. Total points written: 100
  ```

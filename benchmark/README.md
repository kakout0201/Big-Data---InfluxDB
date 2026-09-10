# Benchmark Module — Controlled Dataset & Experiment Framework

Tài liệu hướng dẫn kiến trúc, thiết kế dữ liệu, sinh tập dữ liệu benchmark có khả năng tái lập (Reproducible Benchmark Dataset), đo lường hiệu năng ghi (**Write Throughput Benchmark**) và kiểm thử tính toàn vẹn dữ liệu cho **InfluxDB 3 Core**.

---

## 1. Phân định giữa Demo Dataset và Benchmark Dataset

Để đảm bảo tính khoa học và độ tin cậy trong các bài đo hiệu năng (Performance Benchmarks), hệ thống phân tách độc lập 2 môi trường dữ liệu:

| Tiêu chí | Demo Dataset (Giám sát trực quan) | Benchmark Dataset (Thí nghiệm) |
|---|---|---|
| **Database** | `server_monitoring` | `benchmark_monitoring` |
| **Table** | `server_metrics` | `server_metrics_benchmark` |
| **Mục đích** | Phục vụ trực quan hóa trên Grafana Dashboard và Data Generator ngẫu nhiên theo chu kỳ. | Phục vụ các bài đo lường hiệu năng ghi (Ingestion Throughput), độ trễ truy vấn (Query Latency) và độ nén lưu trữ Parquet. |
| **Tính chất dữ liệu** | Sinh liên tục theo thời gian thực (Uncontrolled streaming). | Tập dữ liệu đóng, kích thước chính xác, có kiểm soát (`--points`), hoàn toàn tái lập (`--seed`). |
| **Retention Policy**| 30 ngày (`30d`) | 30 ngày (`30d`) |
| **Sự cô lập** | Độc lập 100%, không bị ảnh hưởng khi reset benchmark. | Độc lập 100%, không trộn bản ghi từ demo dataset. |

---

## 2. Thiết kế Schema Benchmark

Bảng `server_metrics_benchmark` giữ nguyên schema chuẩn của hệ thống giám sát hạ tầng để phản ánh đúng bài toán thực tế:

### Tags (Metadata định danh - Indexing)
- `host` (`STRING`): Tên máy chủ (`server-01` đến `server-10`).
- `region` (`STRING`): Khu vực địa lý (`hcm`, `hanoi`, `danang`).

### Fields (Giá trị đo đạc - Float64)
- `cpu_usage` (`DOUBLE`): Mức sử dụng CPU (Ràng buộc: `0.0 <= cpu_usage <= 100.0`).
- `memory_usage` (`DOUBLE`): Mức sử dụng RAM (Ràng buộc: `0.0 <= memory_usage <= 100.0`).
- `network_in` (`DOUBLE`): Lưu lượng mạng vào (MB/s) (Ràng buộc: `network_in >= 0.0`).
- `network_out` (`DOUBLE`): Lưu lượng mạng ra (MB/s) (Ràng buộc: `network_out >= 0.0`).
- `error_rate` (`DOUBLE`): Tỷ lệ lỗi hệ thống (%) (Ràng buộc: `0.0 <= error_rate <= 10.0`).

### Timestamp
- Độ chính xác: Nanosecond UTC.
- Ràng buộc: Không chứa giá trị `NULL` ở bất kỳ trường nào.

---

## 3. Quy mô Tập dữ liệu Mục tiêu (Target Dataset Sizes)

Framework hỗ trợ sinh chính xác 5 mốc dữ liệu phục vụ các kịch bản đo lường:

1. **10,000 points (10K):** Kịch bản kiểm thử nền tảng (Baseline test / Unit validation).
2. **50,000 points (50K):** Kịch bản tải nhỏ (Light load).
3. **100,000 points (100K):** Kịch bản tải trung bình (Medium load).
4. **500,000 points (500K):** Kịch bản tải lớn (Heavy load).
5. **1,000,000 points (1M):** Kịch bản đo lường quy mô Big Data (Stress test / Scalability benchmark).

---

## 4. Chiến lược Timestamp & Khả năng Tái lập (Reproducibility)

- **Fixed Start Time:** Cố định thời điểm bắt đầu `FIXED_START_TIME = 2026-09-01T00:00:00Z` (nằm an toàn trong cửa sổ retention 30 ngày của InfluxDB 3).
- **Chronological Progression:**
  - Dữ liệu được sinh theo từng "vòng" (round). Mỗi vòng cách nhau 10 giây (`ROUND_INTERVAL_SECONDS = 10`).
  - Trong mỗi vòng, 10 server lần lượt phát sinh 1 điểm đo đạc telemetry.
  - Timestamp của các server trong cùng vòng được giãn cách 10ms để đảm bảo tính tăng dần đơn điệu và thứ tự thời gian chuẩn xác.
- **Deterministic Pseudo-Random Seed:**
  - Sử dụng cờ `--seed <int>` (mặc định: `42`).
  - Khi chạy lại với cùng số điểm (`--points`) và cùng hạt giống (`--seed`), hệ thống sinh ra chính xác 100% cùng một chuỗi dữ liệu.

---

## 5. Cấu trúc Module Benchmark

```text
benchmark/
├── config.py                 # Cấu hình tham số, kết nối InfluxDB và server distribution
├── generate_dataset.py       # Generator sinh dataset có kiểm soát và batch ingestion
├── validate_dataset.py       # SQL Validator kiểm tra tính đúng đắn và toàn vẹn dữ liệu
├── benchmark_write.py        # Framework đo lường Ingestion Write Throughput
├── README.md                 # Tài liệu đặc tả framework
└── results/                  # Chứa metadata JSON và kết quả đo CSV
    ├── dataset_10000.json
    ├── write_raw.csv         # Chi tiết từng lượt đo riêng lẻ
    ├── write_summary.csv     # Tổng hợp thống kê (Median, Mean, Min, Max)
    └── write_benchmark_metadata.json
```

---

## 6. Hướng dẫn Sử dụng Dataset Generator & Validator

### A. Sinh tập dữ liệu (Generate Dataset)

```bash
# Sinh 10,000 points với seed mặc định (42), batch size 1000, xóa bảng cũ trước khi sinh:
python benchmark/generate_dataset.py --points 10000 --seed 42 --reset

# Sinh 50,000 points với batch size 2000:
python benchmark/generate_dataset.py --points 50000 --batch-size 2000 --reset
```

### B. Kiểm tra tính toàn vẹn (Validate Dataset)

```bash
# Kiểm tra tập dữ liệu benchmark và đối soát số lượng điểm:
python benchmark/validate_dataset.py --expected-points 10000
```

---

## 7. Write Throughput Benchmark Framework

Framework `benchmark/benchmark_write.py` thực hiện đo lường tốc độ ghi dữ liệu (Write Throughput - `points/second`) theo phương pháp thực nghiệm khoa học nghiêm ngặt:

### A. Phương pháp đo lường (Methodology)
1. **Preloading in Memory:** Toàn bộ đối tượng Point được khởi tạo trong bộ nhớ RAM trước khi bật bộ đếm thời gian. Loại bỏ hoàn toàn overhead sinh dữ liệu và tính toán CPU ngẫu nhiên khỏi kết quả đo.
2. **Timing Scope:** Bộ đếm `time.perf_counter()` chỉ bao bọc chính xác vòng lặp gọi `client.write()` gửi các batch dữ liệu qua giao thức HTTPS Line Protocol tới InfluxDB 3.
3. **Pristine Isolation:** Mỗi lượt đo (Trial) đều tự động xóa trắng bảng benchmark (`delete table ... --hard-delete now`) để đảm bảo xuất phát điểm sạch sẽ, không tích tụ phân mảnh.
4. **Warm-up & Repetitions:** Mỗi cấu hình chạy 1 lượt làm nóng (Warm-up - loại bỏ overhead khởi tạo kết nối) và 3 lượt đo chính thức (Measured runs).
5. **Post-Measurement SQL Validation:** Sau khi dừng timer, hệ thống thực thi câu lệnh SQL `SELECT count(*) FROM server_metrics_benchmark` để đối soát tính toàn vẹn của dữ liệu đã ghi. Nếu số lượng bản ghi không khớp chính xác, kết quả sẽ bị hủy bỏ.
6. **Công thức Throughput:**
   $$\text{Throughput (pts/s)} = \frac{\text{Total Points}}{\text{Elapsed Seconds}}$$
7. **Chỉ số đại diện:** Sử dụng **Median Throughput** (trung vị) để loại bỏ ảnh hưởng của các đột biến ngoại lai (outliers).

### B. Cách chạy Benchmark

```bash
# Chạy toàn bộ ma trận Phase A (10K, 50K, 100K x 4 batch sizes):
python benchmark/benchmark_write.py --phase phase-a

# Chạy thử nghiệm nhanh (Smoke test 10K / 1000 batch):
python benchmark/benchmark_write.py --phase smoke

# Chạy tùy biến quy mô và batch size:
python benchmark/benchmark_write.py --phase custom --dataset-sizes 10000,50000 --batch-sizes 1000,5000 --runs 3
```

### C. Kết quả Thực nghiệm Tổng hợp (Phase A Results Matrix)

Dữ liệu đo đạc thực tế từ 48 lượt chạy thực nghiệm độc lập:

| Dataset Size (Points) | Batch Size (Points) | Total Batches | Median Elapsed (s) | Median Throughput (pts/s) | Min Throughput (pts/s) | Max Throughput (pts/s) |
|---|---|---|---|---|---|---|
| **10,000** | 500 | 20 | 19.4425s | **514.34** | 512.23 | 514.86 |
| **10,000** | 1,000 | 10 | 9.4982s | **1,052.83** | 1,050.55 | 1,057.40 |
| **10,000** | 5,000 | 2 | 1.5396s | **6,495.22** | 6,415.12 | 6,529.90 |
| **10,000** | 10,000 | 1 | 0.5597s | **17,868.30** | 17,829.30 | 18,135.45 |
| **50,000** | 500 | 100 | 99.8007s | **501.00** | 500.58 | 503.52 |
| **50,000** | 1,000 | 50 | 49.4881s | **1,010.34** | 1,009.67 | 1,010.68 |
| **50,000** | 5,000 | 10 | 9.5380s | **5,242.18** | 5,238.27 | 5,249.74 |
| **50,000** | 10,000 | 5 | 4.5213s | **11,058.66** | 11,037.38 | 11,089.19 |
| **100,000** | 500 | 200 | 199.4080s | **501.48** | 500.23 | 502.38 |
| **100,000** | 1,000 | 100 | 99.4997s | **1,005.03** | 1,004.92 | 1,006.68 |
| **100,000** | 5,000 | 20 | 19.5367s | **5,118.56** | 5,117.11 | 5,148.76 |
| **100,000** | 10,000 | 10 | 9.5484s | **10,473.00** | 10,462.77 | 10,488.13 |

### D. Nhận xét & Phân tích Khoa học (Key Scientific Insights)
1. **Ảnh hưởng quyết định của Batch Size:**
   - Khi batch size tăng từ `500` lên `10,000`, thông lượng ghi tăng vượt bậc từ **~501 pts/s** lên **~10,473 – 17,868 pts/s** (tăng gấp hơn 20 lần).
   - Nguyên nhân: Việc gom nhóm điểm dữ liệu làm giảm thiểu số lượng HTTP request roundtrips, overhead mã hóa TLS và giải nén WAL trên InfluxDB 3 server.
2. **Tính ổn định của Throughput theo quy mô Dataset:**
   - Với cùng một batch size (ví dụ: `batch_size = 5,000`), thông lượng ghi duy trì ổn định cao trên mọi quy mô: 10K đạt ~6,495 pts/s, 50K đạt ~5,242 pts/s, 100K đạt ~5,118 pts/s.
   - Không xuất hiện hiện tượng sụt giảm hiệu năng hay suy thoái bộ nhớ trong suốt 48 bài đo liên tục.

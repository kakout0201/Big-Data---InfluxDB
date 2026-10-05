# Query Latency Benchmark Module — InfluxDB 3 Core

Tài liệu hướng dẫn kiến trúc, phương pháp đo lường và thực thi bài kiểm thử độ trễ truy vấn (**End-to-End Query Latency Benchmark**) trên **InfluxDB 3 Core (Apache DataFusion / Apache Arrow Flight SQL Engine)**.

---

## 1. Mục tiêu & Phạm vi Đo lường

Bài benchmark tập trung đo lường độ trễ từ đầu đến cuối (End-to-End Latency - mili-giây) từ client Python gửi truy vấn SQL, server DataFusion xử lý và trả về toàn bộ dữ liệu (Result Materialization) trên 3 quy mô tập dữ liệu kiểm soát:
- **10,000 points (10K)**
- **50,000 points (50K)**
- **100,000 points (100K)**

---

## 2. Danh mục 4 Nhóm Truy vấn Chuẩn hóa (Q1 – Q4)

| Mã | Tên Truy vấn | SQL Query | Mục đích & Đặc tả |
|:---:|:---|:---|:---|
| **Q1** | **COUNT** | `SELECT COUNT(*) AS total_records FROM server_metrics_benchmark` | Đo truy vấn tổng hợp đơn giản (Full-table count aggregate) trên toàn bộ tập dữ liệu. |
| **Q2** | **AVG_CPU_BY_HOST** | `SELECT host, AVG(cpu_usage) AS avg_cpu FROM server_metrics_benchmark GROUP BY host ORDER BY avg_cpu DESC` | Đo aggregation + GROUP BY theo Tag dimension `host`, sắp xếp giảm dần (Trả về đúng 10 dòng). |
| **Q3** | **TIME_SERIES_AGGREGATION** | `SELECT date_bin(INTERVAL '5 minutes', time) AS time_bucket, AVG(cpu_usage) AS avg_cpu FROM server_metrics_benchmark GROUP BY time_bucket ORDER BY time_bucket` | Đo time-windowing aggregation sử dụng hàm `date_bin` gom nhóm theo cửa sổ 5 phút. |
| **Q4** | **FILTER_AGGREGATION** | `SELECT region, AVG(cpu_usage) AS avg_cpu, AVG(memory_usage) AS avg_memory, AVG(error_rate) AS avg_error_rate FROM server_metrics_benchmark WHERE region = 'hcm' GROUP BY region` | Đo truy vấn có điều kiện lọc theo Tag (`region = 'hcm'`) kết hợp tính toán đa chỉ số (CPU, RAM, Error Rate). |

---

## 3. Giao thức Đo lường (Benchmark Protocol)

1. **Chuẩn bị Dữ liệu:**
   - Với mỗi quy mô dataset (10K, 50K, 100K), hệ thống tự động reset bảng benchmark và sinh đúng số lượng điểm với `seed=42`, mốc thời gian cố định `2026-09-01T00:00:00Z`.
   - Kiểm tra tính toàn vẹn (Count, 10 hosts, 3 regions, 0 NULLs) trước khi đo.
2. **Timing Scope:**
   - Bộ đếm thời gian `time.perf_counter()` bao bọc chính xác thao tác gửi truy vấn (`client.query()`) và chuyển đổi toàn bộ bản ghi sang danh sách Python (`reader.to_pylist()`).
3. **Warm-up & Measured Runs:**
   - Mỗi cấu hình thực hiện **1 lượt warm-up** (lưu `run_type="warmup"` trong raw data) và **5 lượt đo chính thức** (`run_type="measured"`).
   - Tổng cộng: $3 \times 4 \times 5 = 60$ measured runs + 12 warmup runs = 72 runs.
4. **Điều kiện Cache:**
   > *Query latency benchmark phản ánh điều kiện thực thi truy vấn lặp lại (warm-cache-like condition) phục vụ so sánh có kiểm soát trong cùng một môi trường, không đại diện cho cold-cache latency.*
5. **Chỉ số Đại diện:**
   - Sử dụng **Median Latency (ms)** làm đại lượng chính thức để đánh giá hiệu năng.

---

## 4. Cấu trúc Module

```text
benchmark/
├── config.py                       # Cấu hình kết nối và schema
├── query_queries.py                # Định nghĩa 4 nhóm query chuẩn hóa và validator
├── query_benchmark.py              # Runner thực thi tự động hóa toàn bộ ma trận benchmark
├── QUERY_BENCHMARK_README.md       # Tài liệu hướng dẫn
├── QUERY_BENCHMARK_REPORT.md       # Báo cáo phân tích kết quả thực nghiệm chi tiết
└── results/
    ├── query_latency_raw.csv       # Dữ liệu đo đạc 72 lượt chạy chi tiết
    ├── query_latency_summary.csv   # Thống kê tổng hợp (Median, Min, Max, Mean, StdDev)
    └── query_latency_metadata.json # Metadata đặc tả môi trường phần cứng/phần mềm
```

---

## 5. Hướng dẫn Chạy Benchmark

```bash
# Chạy toàn bộ ma trận (10K, 50K, 100K x 4 queries x 5 runs):
python benchmark/query_benchmark.py

# Tùy chọn tham số CLI:
#   --dataset-sizes : Danh sách quy mô (mặc định: 10000,50000,100000)
#   --runs          : Số lượt đo chính thức (mặc định: 5)
#   --warmup        : Số lượt warm-up (mặc định: 1)
#   --seed          : Hạt giống ngẫu nhiên (mặc định: 42)
```

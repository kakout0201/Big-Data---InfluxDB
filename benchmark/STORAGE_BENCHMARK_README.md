# Storage Efficiency & Physical Parquet Benchmark — InfluxDB 3 Core

Tài liệu đặc tả kiến trúc, phương pháp đo lường và thực thi bài kiểm thử hiệu quả lưu trữ vật lý (**Storage Efficiency & Physical Parquet Measurement**) trên **InfluxDB 3 Core v3.11.2**.

---

## 1. Mục tiêu & Phạm vi

Đo lường dung lượng lưu trữ vật lý thực tế của dữ liệu chuỗi thời gian (Physical Parquet Storage Footprint) trên database benchmark riêng biệt (`benchmark_monitoring.server_metrics_benchmark`) qua 3 quy mô tập dữ liệu kiểm soát:
- **10,000 points (10K)**
- **50,000 points (50K)**
- **100,000 points (100K)**

---

## 2. Kiến trúc Lưu trữ & Vòng đời Dữ liệu InfluxDB 3

1. **Ingestion Layer (Write Ahead Log & Memory Buffer):**
   - Dữ liệu khi được ghi qua API Line Protocol sẽ ghi tuần tự vào file WAL (`node0/wal/*.wal`) và giữ trong bộ đệm bộ nhớ (Arrow RecordBatches). Dữ liệu có thể truy vấn được ngay lập tức bằng SQL thông qua DataFusion.
2. **Persistence Layer (Parquet Object Store):**
   - Tiến trình nền (Background Compactor / Persister) gom nhóm các bản ghi từ buffer/WAL và ghi nén thành các tệp Parquet theo phân vùng thời gian (`node0/dbs/<db_id>/<table_id>/<date>/<time_partition>/<id>.parquet`).
   - Metadata của các file Parquet đã được nén hoàn tất được đăng ký vào bảng hệ thống `system.parquet_files`.

---

## 3. Phương pháp Đo lường 3 Lớp (Three-Tier Measurement)

- **Lớp 1 — Primary Measurement (`system.parquet_files`):**
  Truy vấn trực tiếp metadata hệ thống của InfluxDB 3 với cơ chế xử lý lỗi tường minh:
  ```sql
  SELECT
      table_name,
      path,
      size_bytes,
      row_count,
      min_time,
      max_time
  FROM system.parquet_files
  WHERE table_name = 'server_metrics_benchmark'
  ORDER BY path
  ```
- **Lớp 2 — Secondary Validation (Filesystem Cross-Check):**
  Sử dụng `docker exec stat` để đọc trực tiếp kích thước byte vật lý của từng file Parquet trên container filesystem và so sánh với `size_bytes` từ metadata (`size_match`).
- **Lớp 3 — Estimated Uncompressed Logical Payload Model:**
  Mô hình kích thước logic thô dựa trên giá trị dữ liệu chưa nén:
  $$\text{Logical Payload} = N \times (8\text{B time} + 9\text{B host} + 4.5\text{B avg region} + 40\text{B fields}) = N \times 61.5\text{ bytes}$$

---

## 4. Cấu trúc Module

```text
benchmark/
├── storage_measurement.py          # Module đo lường metadata, filesystem stat và logical payload
├── storage_benchmark.py            # Runner tự động hóa quy trình benchmark lưu trữ
├── test_storage_logic.py           # Bộ unit & smoke test kiểm thử logic đo lường
├── results/
│   ├── storage_raw.csv             # Dữ liệu đo đạc chi tiết từng lần chạy
│   ├── storage_summary.csv         # Bảng tổng hợp theo dataset scale
│   └── storage_metadata.json       # Metadata đặc tả môi trường và phương pháp
├── STORAGE_INSPECTION_REPORT.md    # Báo cáo kết quả kiểm tra Phase 0
├── STORAGE_BENCHMARK_README.md     # Tài liệu hướng dẫn
└── STORAGE_BENCHMARK_REPORT.md     # Báo cáo phân tích thực nghiệm chi tiết
```

---

## 5. Hướng dẫn Chạy Benchmark

```bash
# Chạy bộ unit/smoke test kiểm thử logic đo lường:
python benchmark/test_storage_logic.py

# Thực thi toàn bộ benchmark lưu trữ:
python benchmark/storage_benchmark.py

# Tùy chọn tham số CLI:
#   --dataset-sizes : Quy mô tập dữ liệu (mặc định: '10000,50000,100000')
#   --poll-interval : Chu kỳ polling kiểm tra persistence (mặc định: 1.0s)
#   --stable-checks : Số lần kiểm tra ổn định liên tiếp (mặc định: 3)
#   --timeout       : Thời gian timeout polling (mặc định: 60.0s)
#   --seed          : Hạt giống ngẫu nhiên (mặc định: 42)
```

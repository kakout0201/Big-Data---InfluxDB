# QUERY LATENCY BENCHMARK REPORT — INFLUXDB 3 CORE

**Dự án:** Nghiên cứu InfluxDB 3 và xây dựng hệ thống giám sát dữ liệu chuỗi thời gian thời gian thực  
**Môn học:** Big Data  
**Thời gian thực nghiệm:** 02/09/2026  
**Trạng thái:** **PASS (100% Validated)**

---

## A. Objective (Mục tiêu Thực nghiệm)

Đo lường và đánh giá **End-to-End Query Latency** (mili-giây) của **InfluxDB 3 Core** (sử dụng engine Apache DataFusion, Apache Arrow Flight SQL và định dạng Parquet) trên 4 nhóm câu truy vấn phân tích chuỗi thời gian điển hình (Q1 – Q4) qua các quy mô tập dữ liệu kiểm soát (**10,000**, **50,000**, và **100,000** points).

---

## B. Experimental Environment (Môi trường Thực nghiệm)

- **Hệ điều hành:** Windows 11 Pro 64-bit (Build 26100, x86_64 / AMD64)
- **Container Engine:** Docker Desktop 29.5.2 / Docker Compose v5.1.3
- **Database Server:** InfluxDB 3 Core v3.11.2 (`influxdb:3-core`)
- **Query Processing Engine:** Apache DataFusion / Apache Arrow Flight SQL (Port 8181 HTTPS / gRPC)
- **Môi trường Client:** Python 3.11.9 (Thư viện `influxdb-client-3` v0.21.0, `pyarrow` v21.0.0)
- **Database Thử nghiệm:** `benchmark_monitoring` (Table: `server_metrics_benchmark`)
- **Database Demo:** `server_monitoring` (Bảo toàn nguyên vẹn 282 bản ghi)

---

## C. Dataset Specification (Đặc tả Tập dữ liệu)

- **Quy mô đo lường:** 10,000 points, 50,000 points, 100,000 points.
- **Hạt giống (Seed):** `seed = 42` (Đảm bảo 100% tính tái lập).
- **Mốc thời gian (Base Timestamp):** `2026-09-01T00:00:00Z` (Nằm trong retention 30 ngày).
- **Schema:**
  - **Tags:** `host` (10 nodes `server-01` → `server-10`), `region` (3 vùng `hcm`, `hanoi`, `danang`).
  - **Fields:** `cpu_usage`, `memory_usage`, `network_in`, `network_out`, `error_rate` (`DOUBLE`).
  - **Timestamp:** Nanosecond UTC.

---

## D. Query Definitions (Định nghĩa 4 Nhóm Truy vấn)

### 1. Q1 — COUNT (Full-table Aggregate)
```sql
SELECT COUNT(*) AS total_records
FROM server_metrics_benchmark
```
*Mục đích:* Đo tốc độ quét metadata / row-group stats và đếm tổng số bản ghi.

### 2. Q2 — AVG CPU BY HOST (Dimension Group By)
```sql
SELECT
    host,
    AVG(cpu_usage) AS avg_cpu
FROM server_metrics_benchmark
GROUP BY host
ORDER BY avg_cpu DESC
```
*Mục đích:* Đo hiệu năng gom nhóm (GROUP BY) và tính toán aggregate trên Tag dimension `host` (Trả về đúng 10 dòng).

### 3. Q3 — TIME_SERIES_AGGREGATION (Windowing with `date_bin`)
```sql
SELECT
    date_bin(INTERVAL '5 minutes', time) AS time_bucket,
    AVG(cpu_usage) AS avg_cpu
FROM server_metrics_benchmark
GROUP BY time_bucket
ORDER BY time_bucket
```
*Mục đích:* Đo hiệu năng tính toán chia khung thời gian (time-windowing) bằng hàm chuẩn `date_bin` với cửa sổ 5 phút.

### 4. Q4 — FILTER_AGGREGATION (Tag Filtering + Multi-metric Aggregate)
```sql
SELECT
    region,
    AVG(cpu_usage) AS avg_cpu,
    AVG(memory_usage) AS avg_memory,
    AVG(error_rate) AS avg_error_rate
FROM server_metrics_benchmark
WHERE region = 'hcm'
GROUP BY region
```
*Mục đích:* Đo hiệu năng lọc dữ liệu theo Tag (`WHERE region = 'hcm'`) kết hợp tính toán đồng thời 3 chỉ số tổng hợp.

---

## E. Benchmark Protocol (Giao thức Thực nghiệm)

- **Quy trình chạy:** Với từng dataset size (10K, 50K, 100K) $\to$ Reset table $\to$ Sinh dataset chính xác $\to$ Validate $\to$ Chạy Q1..Q4.
- **Lượt chạy:** Mỗi cấu hình chạy **1 warm-up run** và **5 measured runs**.
- **Tổng số lượt chạy:** $3 \times 4 \times 1 = 12$ warm-up runs + $3 \times 4 \times 5 = 60$ measured runs = **72 lượt truy vấn**.
- **Timing Scope:** `time.perf_counter()` bao bọc chính xác thao tác gửi truy vấn và materialize toàn bộ kết quả (`reader.to_pylist()`).
- **Ghi chú về Cache:**
  > *Query latency benchmark phản ánh điều kiện thực thi truy vấn lặp lại (repeated-query / warm-cache-like condition) phục vụ so sánh có kiểm soát trong cùng một môi trường, không đại diện cho cold-cache latency.*

---

## F. Raw Result Validation (Đối soát Kết quả)

- **Dataset Validation:** Cả 3 tập dữ liệu 10K, 50K, 100K đều vượt qua 100% bộ kiểm tra tự động trước khi đo (Exact COUNT, 10 hosts, 3 regions, 0 NULLs).
- **Execution Success Rate:** **60 / 60 measured runs thành công (100% PASS)**, không có truy vấn nào bị lỗi cú pháp, timeout hay trả về sai cấu trúc.
- **Materialization Validation:**
  - Q1: Trả về chính xác 1 dòng với giá trị đếm khớp với quy mô dataset.
  - Q2: Trả về chính xác 10 dòng (10 server hosts).
  - Q3: Trả về đúng số lượng khung thời gian (34 buckets cho 10K, 167 buckets cho 50K, 334 buckets cho 100K).
  - Q4: Trả về chính xác 1 dòng cho khu vực `hcm`.
- **Đánh giá Bất thường (Anomaly Evaluation):**
  > *Không ghi nhận lỗi thực thi, timeout hoặc mất dữ liệu. Tuy nhiên, latency không tăng đơn điệu theo kích thước dataset ở tất cả query archetype. Đây là một hiện tượng cần được thận trọng khi diễn giải. Benchmark hiện tại không được thiết kế để cô lập nguyên nhân của hiện tượng này.*

---

## G. Summary Results (Bảng Tổng hợp Độ trễ Thực tế)

Số liệu đo đạc thực tế được tổng hợp từ file `benchmark/results/query_latency_summary.csv`:

| Dataset Size | Query ID | Query Archetype | Measured Runs | **Median Latency (ms)** | Min Latency (ms) | Max Latency (ms) | Mean Latency (ms) | StdDev (ms) | Success |
|:---:|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **10,000** | **Q1** | COUNT | 5 | **8.611 ms** | 6.979 ms | 16.169 ms | 10.261 ms | 3.706 ms | **PASS** |
| **10,000** | **Q2** | AVG_CPU_BY_HOST | 5 | **15.527 ms** | 11.365 ms | 28.397 ms | 18.948 ms | 7.163 ms | **PASS** |
| **10,000** | **Q3** | TIME_SERIES_AGGREGATION | 5 | **18.116 ms** | 12.709 ms | 23.845 ms | 17.531 ms | 4.538 ms | **PASS** |
| **10,000** | **Q4** | FILTER_AGGREGATION | 5 | **12.753 ms** | 11.644 ms | 18.653 ms | 14.253 ms | 3.019 ms | **PASS** |
| **50,000** | **Q1** | COUNT | 5 | **19.492 ms** | 16.287 ms | 32.785 ms | 21.254 ms | 6.583 ms | **PASS** |
| **50,000** | **Q2** | AVG_CPU_BY_HOST | 5 | **33.004 ms** | 30.483 ms | 37.235 ms | 33.258 ms | 2.588 ms | **PASS** |
| **50,000** | **Q3** | TIME_SERIES_AGGREGATION | 5 | **33.040 ms** | 26.248 ms | 39.274 ms | 33.819 ms | 5.363 ms | **PASS** |
| **50,000** | **Q4** | FILTER_AGGREGATION | 5 | **39.377 ms** | 36.587 ms | 44.294 ms | 40.423 ms | 3.224 ms | **PASS** |
| **100,000** | **Q1** | COUNT | 5 | **33.180 ms** | 23.687 ms | 37.542 ms | 30.833 ms | 6.094 ms | **PASS** |
| **100,000** | **Q2** | AVG_CPU_BY_HOST | 5 | **32.999 ms** | 30.189 ms | 34.115 ms | 32.312 ms | 1.973 ms | **PASS** |
| **100,000** | **Q3** | TIME_SERIES_AGGREGATION | 5 | **28.360 ms** | 27.316 ms | 31.532 ms | 28.695 ms | 1.670 ms | **PASS** |
| **100,000** | **Q4** | FILTER_AGGREGATION | 5 | **25.498 ms** | 21.701 ms | 28.012 ms | 25.117 ms | 2.806 ms | **PASS** |

---

## H. Scientific Observations (Nhận xét Khoa học dựa trên Số liệu Thực tế)

1. **Dải Độ trễ Quan sát được:**
   - Trong phạm vi thử nghiệm, median latency của cả bốn nhóm truy vấn nằm trong khoảng **8.611–39.377 ms**.
   - Một số measured run có latency cao hơn median, với giá trị tối đa quan sát được là **44.294 ms** (tại Q4 - 50K).
   - Kết quả này cho thấy các truy vấn được kiểm thử có độ trễ ở mức vài chục mili-giây trong môi trường benchmark, nhưng không đủ để kết luận về SLA hoặc khả năng đáp ứng của một hệ thống production real-time.
2. **Quan sát Cụ thể về Nhóm Truy vấn Q4:**
   - Giá trị Median Latency của Q4:
     - **10K Points:** `12.753 ms`
     - **50K Points:** `39.377 ms`
     - **100K Points:** `25.498 ms`
   - Q4 cho thấy median latency tại 50K cao hơn 100K. Kết quả này cho thấy quan hệ giữa dataset size và query latency trong thử nghiệm không hoàn toàn đơn điệu. Các yếu tố runtime/cache có thể ảnh hưởng, nhưng benchmark hiện tại không đủ để xác định nguyên nhân.
3. **Độ Biến thiên giữa các Lượt chạy:**
   - Độ lệch chuẩn (StdDev) giữa 5 lượt chạy chính thức của mỗi cấu hình dao động trong khoảng **1.670 ms đến 7.163 ms**.
4. **Lưu ý Khoa học về Kiến trúc:**
   - Các thành phần cốt lõi của InfluxDB 3 Core (Apache Arrow, Apache DataFusion, định dạng cột Parquet) là nền tảng kiến trúc của hệ thống; benchmark này chỉ đo kết quả thực nghiệm và không cô lập đóng góp của từng thành phần.

---

## I. Limitations (Giới hạn Thực nghiệm)

Để đảm bảo tính khách quan và khoa học, các giới hạn của bài benchmark này cần được ghi nhận rõ ràng:
1. **Phạm vi hệ quản trị:** Chỉ benchmark duy nhất trên InfluxDB 3 Core, không có baseline đối chứng trực tiếp với MySQL, PostgreSQL hay các time-series database khác.
2. **Tải người dùng:** Không benchmark concurrent users hoặc tải truy vấn đồng thời đa luồng (chỉ đo tuần tự single-client).
3. **Điều kiện bộ nhớ đệm:** Không benchmark cold-cache (các lượt chạy được thực hiện liên tiếp trong điều kiện warm-cache-like).
4. **Quy mô mẫu:** Mỗi cấu hình chỉ thực hiện 5 measured runs / query / dataset size.
5. **Giám sát tài nguyên phần cứng:** Không đo lường mức tiêu thụ CPU, RAM và Disk I/O phân lập cho từng câu lệnh truy vấn.
6. **Đánh giá SLA:** Không đánh giá các cam kết dịch vụ (SLA) hoặc môi trường chịu tải thực tế trong môi trường production.
7. **Khả năng mở rộng (Scalability):** Không thể suy diễn khả năng mở rộng vô hạn ngoài dải quy mô đã kiểm thử từ 10,000 đến 100,000 bản ghi.

---

## J. Final Conclusion (Kết luận)

**TASK 8 PASS về mặt implementation và experimental execution.** Kết quả được sử dụng để mô tả query latency trong môi trường benchmark đã kiểm soát, không được sử dụng để đưa ra các tuyên bố về production SLA hoặc so sánh hiệu năng với hệ quản trị CSDL khác.

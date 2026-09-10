# STORAGE INSPECTION REPORT — INFLUXDB 3 CORE (PHASE 0)

**Dự án:** Nghiên cứu InfluxDB 3 và xây dựng hệ thống giám sát dữ liệu chuỗi thời gian thời gian thực  
**Môn học:** Big Data  
**Thời gian kiểm tra:** 02/09/2026  
**Giai đoạn:** **PHASE 0 — INSPECTION ONLY (Read-Only)**  
**Trạng thái Kết luận:** **`PASS WITH LIMITATION — storage can be measured using controlled before/after delta`**

---

## A. InfluxDB Version

- **Phiên bản Server:** InfluxDB 3 Core v3.11.2 (`influxdb:3-core`)
- **Docker Image Digest:** `sha256:f4a6d4a76f0ed0a196cc997da472cd0b7ae52a766430493a1bead807ab8c1217`
- **Hệ điều hành nền:** Ubuntu 24.04 LTS (x86_64 / Linux container trên Windows 11 Docker Desktop)
- **Engine cốt lõi:** Apache DataFusion, Apache Arrow Flight SQL, Parquet Object Store Storage Engine.

---

## B. Docker Storage Configuration

- **Named Volume Mount:**
  - **Tên Volume:** `influxdb3_data`
  - **Host Path (Docker Desktop):** `/var/lib/docker/volumes/influxdb3_data/_data`
  - **Container Destination:** `/home/influxdb3/.influxdb3` (Quyền: `rw`, user `influxdb3`)
- **Biến môi trường lưu trữ:**
  - `INFLUXDB3_DATA_DIR=/home/influxdb3/.influxdb3`
  - `INFLUXDB3_OBJECT_STORE=file`
  - `INFLUXDB3_NODE_ID=node0`

---

## C. Actual Storage Directory Layout

Cấu trúc cây thư mục thực tế bên trong container tại `/home/influxdb3/.influxdb3/node0`:

```text
/home/influxdb3/.influxdb3/node0/
├── catalog/                          # Internal metadata catalog (sqlite/meta)
├── db-indices/                       # Index files ánh xạ cho từng database (db 1, db 2)
│   ├── 1/                            # Database 1 (server_monitoring)
│   └── 2/                            # Database 2 (benchmark_monitoring)
├── dbs/                              # Parquet Object Store files
│   ├── 1/                            # Database 1 (server_monitoring)
│   └── 2/                            # Database 2 (benchmark_monitoring)
├── snapshots/                        # Snapshot checkpoints
├── table-index-conversion-completed  # Marker file
└── wal/                              # Write Ahead Log segments (*.wal)
```

---

## D. Parquet Location & System Metadata Mapping

1. **Vị trí tệp Parquet trên Filesystem:**
   - Các tệp Parquet được lưu trữ theo cấu trúc phân cấp thời gian và phân vùng:
     `/home/influxdb3/.influxdb3/node0/dbs/<db_id>/<table_id>/<date>/<time_partition>/<file_id>.parquet`
   - Ví dụ quan sát được:
     - Database `server_monitoring` (DB ID `1`): `/home/influxdb3/.influxdb3/node0/dbs/1/0/2026-09-02/04-20/0000001812.parquet`
     - Database `benchmark_monitoring` (DB ID `2`): `/home/influxdb3/.influxdb3/node0/dbs/2/46/2026-09-01/13-10/0000001812.parquet`
2. **Metadata Table Mapping (`system.parquet_files`):**
   - InfluxDB 3 Core cung cấp bảng hệ thống `system.parquet_files` trong mỗi database, cho phép truy vấn trực tiếp danh sách tệp Parquet đã được persist:
     - `table_name` (`STRING`): Tên bảng tương ứng.
     - `path` (`STRING`): Đường dẫn tương đối của file Parquet.
     - `size_bytes` (`BIGINT`): Dung lượng byte vật lý chính xác của từng file.
     - `row_count` (`BIGINT`): Số dòng bản ghi chứa trong file Parquet.
     - `min_time`, `max_time` (`BIGINT`): Dải timestamp (nanoseconds).

---

## E. WAL Location & Ingestion Lifecycle

- **Vị trí WAL:** `/home/influxdb3/.influxdb3/node0/wal/`
- **Dung lượng hiện tại:** ~116 MB (chứa các đoạn log `0000000xxxx.wal` được ghi tuần tự khi nhận Line Protocol).
- **Vòng đời dữ liệu:**
  1. Khi client gọi API `write()`, dữ liệu được ghi tức thời vào WAL và lưu trong bộ đệm in-memory buffer.
  2. Tiến trình nền (Background Compactor / Persister) sẽ gom nhóm các bản ghi từ WAL / buffer và nén thành các tệp Parquet theo từng partition thời gian dưới thư mục `dbs/`.
  3. Khi hoàn tất flush, thông tin file Parquet mới được đăng ký vào `system.parquet_files`.

---

## F. Database / Table Isolation Feasibility

- **Mức độ cô lập Database:** **RẤT TỐT**.
  - `server_monitoring` (Database ID `1`) và `benchmark_monitoring` (Database ID `2`) nằm ở hai nhánh thư mục vật lý hoàn toàn tách biệt (`dbs/1/` và `dbs/2/`).
  - Bảng `system.parquet_files` trong `benchmark_monitoring` chỉ hiển thị các file thuộc database benchmark.
- **Mức độ cô lập Table nội bộ:** **CÓ GIỚI HẠN**.
  - Khi xóa bảng benchmark (`delete table ...`), InfluxDB 3 thực hiện soft-delete (đổi tên table thành `server_metrics_benchmark-<timestamp>`) và giữ lại file Parquet cũ trên đĩa cho đến khi cơ chế tombstone compaction thu hồi.
  - Do đó, nếu chỉ đo tổng dung lượng thư mục `dbs/2/`, kết quả sẽ bị cộng dồn cả các file Parquet của các bảng cũ đã xóa.
  - Tuy nhiên, ta có thể lọc chính xác các file Parquet đang gắn với bảng active hiện tại bằng cách truy vấn `system.parquet_files WHERE table_name = 'server_metrics_benchmark'` hoặc đối soát delta.

---

## G. Persistence Behavior Observed

1. Dữ liệu mới ghi vào sẽ tồn tại trong WAL trước khi được compactor nén thành Parquet.
2. Nếu đo storage ngay lập tức sau khi write mà không chờ chu kỳ flush, `system.parquet_files` của bảng có thể chưa ghi nhận đầy đủ dung lượng Parquet cuối cùng.
3. Cần áp dụng chiến lược chờ ổn định (Stability Polling Window): kiểm tra liên tục trạng thái của `system.parquet_files` và filesystem cho đến khi dung lượng Parquet không đổi qua $N$ lần kiểm tra liên tiếp.

---

## H. Recommended Measurement Methodology

Để đo lường dung lượng lưu trữ và hiệu quả nén một cách khoa học và trung thực, đề xuất phương pháp đo 3 lớp:

1. **Physical Parquet Size (Metric chính):**
   - Truy vấn bảng hệ thống:
     ```sql
     SELECT
         count(*) AS parquet_file_count,
         sum(size_bytes) AS total_parquet_bytes,
         sum(row_count) AS total_parquet_rows
     FROM system.parquet_files
     WHERE table_name = 'server_metrics_benchmark'
     ```
   - Đối soát với dung lượng các file Parquet thực tế trên filesystem container.
2. **Controlled Before/After Delta (Metric đối chứng):**
   - Ghi nhận `storage_before_bytes` trên filesystem thư mục `node0/dbs/2/` trước khi sinh dataset.
   - Sinh dataset có kiểm soát (`10K`, `50K`, `100K`).
   - Chờ persistence ổn định (Stability polling).
   - Ghi nhận `storage_after_bytes` và tính $\Delta_{\text{storage}} = \text{storage\_after} - \text{storage\_before}$.
3. **Estimated Logical Data Size (Mô hình ước tính dữ liệu thô):**
   - Định nghĩa công thức tính kích thước logic thô của dữ liệu đo đạc (Uncompressed Raw Payload):
     $$\text{Logical Size} = N \times (\text{size}(time) + \sum \text{size}(tags) + \sum \text{size}(fields))$$
     - `time`: 8 bytes (Int64 nanoseconds).
     - `host`: 9 bytes trung bình (ASCII string `server-01` .. `server-10`).
     - `region`: 4–6 bytes trung bình (ASCII string `hcm`, `hanoi`, `danang`).
     - `5 fields`: $5 \times 8\text{ bytes} = 40\text{ bytes}$ (Float64 IEEE 754).
     - Tổng ước lượng $\approx 62\text{ bytes / point}$.
4. **Storage Ratio & Storage Reduction (%):**
   $$\text{Storage Ratio} = \frac{\text{Physical Parquet Bytes}}{\text{Estimated Logical Data Size}}$$
   $$\text{Storage Reduction (\%)} = \left(1 - \frac{\text{Physical Parquet Bytes}}{\text{Estimated Logical Data Size}}\right) \times 100$$

---

## I. Risks & Limitations

1. **Độ trễ Asynchronous Flushing:** Không thể đảm bảo Parquet flush diễn ra tức thì sau lệnh write. Phải có cơ chế polling với timeout.
2. **WAL Overhead:** WAL chứa dữ liệu chung của toàn node, do đó không dùng dung lượng thư mục `wal/` để tính dung lượng của từng bảng riêng lẻ.
3. **Không so sánh phiến diện:** Không so sánh dung lượng Parquet của InfluxDB với file CSV chưa nén hoặc các hệ CSDL khác chưa được benchmark trực tiếp.

---

## J. PASS / BLOCKED Conclusion

### **PASS WITH LIMITATION — storage can be measured using controlled before/after delta**

*Lý do:* Hệ thống cung cấp đầy đủ bảng metadata `system.parquet_files` và cấu trúc thư mục phân cấp `dbs/2/` cho phép định danh và đo lường dung lượng tệp Parquet thực tế. Phép đo cần có cơ chế chờ ổn định persistence (stability polling) và bóc tách rõ ràng giữa tệp Parquet và WAL.

# KỊCH BẢN TRÌNH DIỄN HỆ THỐNG TRỰC TIẾP (LIVE DEMO SCRIPT)

**Học phần:** Dữ liệu lớn (Big Data) — Báo cáo cơ sở lý thuyết đồ án môn học  
**Đề tài:** Nghiên cứu InfluxDB 3 và Xây dựng Hệ thống Giám sát Dữ liệu Chuỗi Thời gian  
**Sinh viên thực hiện:** Vạn Trung Tính  
**Thời lượng thực hiện:** 3 – 5 phút (Khuyến nghị chuẩn: **3 phút 30 giây**)  
**Mục tiêu cốt lõi:** Minh chứng thực tế tính khả thi của pipeline: từ phát sinh telemetry (10 máy chủ qua HTTP Line Protocol) ➔ Lưu trữ bộ nhớ InfluxDB 3 (Arrow Write Buffer & WAL) ➔ Truy vấn phân tích DataFusion SQL ➔ Trực quan hóa Dashboard Grafana qua Apache Arrow Flight SQL.

---

## 1. BẢNG TIẾN TRÌNH THỜI GIAN (DEMO TIMELINE)

| Mốc thời gian | Phân đoạn | Mục tiêu thao tác | Trọng tâm lời thoại |
| :---: | :--- | :--- | :--- |
| **0:00 – 0:30** | **Bước 1: Hạ tầng Docker** | Chạy `docker compose ps` | Khẳng định 2 dịch vụ InfluxDB 3 Core và Grafana đang vận hành ổn định. |
| **0:30 – 1:15** | **Bước 2: Nạp Telemetry** | Chạy `generator.py` (15 batch) | Minh họa luồng Ingestion 10 server qua Line Protocol, nhấn mạnh tốc độ nạp vào RAM Buffer. |
| **1:15 – 2:15** | **Bước 3: Phân tích SQL** | Chạy 2 câu SQL trên CLI | Khám phá dữ liệu tức thời và tính toán vector hóa SIMD (`GROUP BY host`, `date_bin`). |
| **2:15 – 3:30** | **Bước 4: Grafana Live** | Trình duyệt Web (Port 3000) | Trình diễn 12 panels cập nhật gần thời gian thực qua giao thức Arrow Flight SQL (gRPC). |
| **3:30 – 4:00** | **Bước 5: Kết luận Demo** | Tóm tắt pipeline | Khẳng định tính trọn vẹn của PoC và chuyển sang phiên hỏi đáp (Q&A). |

---

## 2. CHECKLIST CHUẨN BỊ TRƯỚC BÁO CÁO (PRE-DEMO CHECKLIST)

Chuẩn bị sẵn 3 cửa sổ làm việc trên màn hình máy tính:

- [ ] **Cửa sổ 1 (Terminal 1 - PowerShell):**  
  Mở tại thư mục: `D:\Kỳ 1 năm 4\Big Data\INFLUXDB`  
  Kích hoạt môi trường ảo: `.\.venv\Scripts\Activate.ps1`  
  *(Dùng để kiểm tra Docker và chạy Python Data Generator)*
- [ ] **Cửa sổ 2 (Terminal 2 - PowerShell):**  
  Mở tại cùng thư mục, sẵn sàng thực thi các câu lệnh truy vấn SQL.
- [ ] **Cửa sổ 3 (Trình duyệt Web Google Chrome / Edge):**  
  Mở sẵn tab Grafana: `http://localhost:3000`  
  Đăng nhập sẵn tài khoản: `admin` / `GrafanaSec2026_x8K9m#SecurePass`  
  Mở sẵn Dashboard: **`Server Monitoring — InfluxDB 3`**  
  Cài đặt góc trên bên phải:  
  * Khoảng thời gian (Time Range): **`Last 5 minutes`**  
  * Tần suất làm mới (Auto Refresh): **`5s`**

---

## 3. TIẾN TRÌNH THAO TÁC CHI TIẾT TỪNG BƯỚC

---

### BƯỚC 1: KIỂM TRA TRẠNG THÁI HẠ TẦNG DOCKER (0:00 – 0:30)

* **Vị trí thao tác:** Terminal 1  
* **Câu lệnh thực thi:**
  ```powershell
  docker compose ps
  ```
* **Màn hình hiển thị mong đợi:**
  ```text
  NAME             IMAGE                  COMMAND                  SERVICE    CREATED         STATUS         PORTS
  grafana          grafana/grafana:11.5.2 "/run.sh"                grafana    2 hours ago     Up 2 hours     0.0.0.0:3000->3000/tcp
  influxdb3-core   influxdb:3-core        "/entrypoint.sh infl…"   influxdb   2 hours ago     Up 2 hours     0.0.0.0:8181->8181/tcp
  ```
* **Lời thoại diễn thuyết:**
  > *"Kính thưa quý Thầy/Cô trong Hội đồng, để minh chứng cho các luận điểm lý thuyết vừa trình bày, em xin phép bước vào phần trình diễn thực nghiệm (Live Demo) mô hình Proof-of-Concept.*  
  > *Trước hết, em kiểm tra trạng thái hạ tầng thực nghiệm qua lệnh `docker compose ps`. Hệ thống hiện đang vận hành 2 container độc lập: InfluxDB 3 Core đóng vai trò Time-Series Database engine tiếp nhận dữ liệu tại cổng 8181, và Grafana phiên bản 11.5 đóng vai trò trực quan hóa tại cổng 3000. Cả hai dịch vụ đều đang ở trạng thái Up và sẵn sàng."*

---

### BƯỚC 2: KHỞI ĐỘNG PYTHON TELEMETRY GENERATOR (0:30 – 1:15)

* **Vị trí thao tác:** Terminal 1  
* **Câu lệnh thực thi:** (Chạy 15 batch liên tiếp, mỗi batch cách nhau 1 giây)
  ```powershell
  python python/generator.py --interval 1.0 --iterations 15
  ```
* **Màn hình hiển thị mong đợi:**
  ```text
  [INFO] Connecting to InfluxDB 3 Core (URL: https://localhost:8181)
  [INFO] Target Database: server_monitoring
  [INFO] Servers: 10 across 3 regions (hcm, hanoi, danang)
  [INFO] Iteration 1/15 — wrote 10 points (timestamp: 2026-09-10T...)
  [INFO] Iteration 2/15 — wrote 10 points (timestamp: 2026-09-10T...)
  [INFO] Iteration 3/15 — wrote 10 points (timestamp: 2026-09-10T...)
  ...
  [INFO] Iteration 15/15 — wrote 10 points (timestamp: 2026-09-10T...)
  [SUCCESS] Successfully sent 150 points across 15 iterations.
  ```
* **Lời thoại diễn thuyết:**
  > *"Tiếp theo, em khởi động module Python Telemetry Generator. Script này mô phỏng dữ liệu giám sát của 10 máy chủ phân bố trên 3 miền: 4 máy tại TP.HCM, 3 máy tại Hà Nội và 3 máy tại Đà Nẵng.*  
  > *Mỗi giây, script sẽ đóng gói 10 điểm đo — gồm chỉ số CPU, Memory, Network I/O và Error Rate — theo chuẩn định dạng Line Protocol siêu nhẹ và đẩy trực tiếp vào InfluxDB 3 qua giao thức HTTP an toàn.*  
  > *Dữ liệu gửi đến lập tức được InfluxDB 3 đưa vào Write Buffer trong RAM dưới dạng mảng Apache Arrow và ghi đồng thời vào nhật ký Write-Ahead Log trên đĩa để đảm bảo an toàn."*

---

### BƯỚC 3: TRUY VẤN DỮ LIỆU TỨC THÌ BẰNG DATAFUSION SQL (1:15 – 2:15)

* **Vị trí thao tác:** Chuyển sang Terminal 2  

#### Thao tác 3.1: Lấy 5 bản ghi mới nhất vừa nạp
* **Câu lệnh thực thi:**
  ```powershell
  docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT time, host, region, cpu_usage, memory_usage FROM server_metrics ORDER BY time DESC LIMIT 5;"
  ```
* **Màn hình hiển thị mong đợi:** Bảng hiển thị 5 dòng số liệu kèm timestamp nano-giây vừa nạp ở Bước 2.
* **Lời thoại diễn thuyết:**
  > *"Ngay khi dữ liệu vừa phát sinh, em thực thi câu lệnh SQL tiêu chuẩn để kiểm tra 5 bản ghi mới nhất.*  
  > *Nhờ cơ chế In-Memory Arrow Buffer của InfluxDB 3, dữ liệu mới nạp có thể truy vấn ngay tức thì với độ trễ mili-giây mà không cần đợi tiến trình compactor nén hay ghi xong file Parquet xuống đĩa."*

#### Thao tác 3.2: Thống kê tổng hợp theo Host (Vectorized Execution)
* **Câu lệnh thực thi:**
  ```powershell
  docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT host, round(avg(cpu_usage), 2) AS avg_cpu, max(cpu_usage) AS max_cpu, count(*) AS total_points FROM server_metrics GROUP BY host ORDER BY avg_cpu DESC;"
  ```
* **Màn hình hiển thị mong đợi:** Bảng tổng hợp xếp hạng 10 máy chủ giảm dần theo `avg_cpu`.
* **Lời thoại diễn thuyết:**
  > *"Tiếp theo là câu lệnh phân tích tổng hợp: tính CPU trung bình, CPU đỉnh điểm và tổng số điểm đo của từng node máy chủ.*  
  > *Query engine Apache DataFusion sử dụng tập lệnh SIMD tính toán song song trực tiếp trên mảng cột trong bộ nhớ, trả về bảng xếp hạng phụ tải giữa các server ngay lập tức."*

---

### BƯỚC 4: TRỰC QUAN HÓA TRÊN GRAFANA DASHBOARD QUA ARROW FLIGHT SQL (2:15 – 3:30)

* **Vị trí thao tác:** Chuyển sang Cửa sổ 3 (Trình duyệt Web Grafana tại `http://localhost:3000`)
* **Hành động của diễn giả:** Dùng chuột trỏ lần lượt vào 3 khu vực trọng tâm của Dashboard:
  1. **Hàng 1 (Góc trên):**
     * Widget **Total Records**: Con số đo đạc tăng lên sau đợt phát sinh dữ liệu vừa rồi.
     * Widget **Average CPU Usage** & **Memory Usage**: Đồng hồ Gauge hiển thị chỉ số sức khỏe tổng thể.
  2. **Hàng 2 (Chính giữa):**
     * Panel **CPU Usage Over Time**: Đồ thị đường hiển thị 10 chuỗi tín hiệu thời gian thực của 10 máy chủ, phân biệt rõ nét bằng các màu sắc khác nhau.
     * Panel **Network Traffic (MB/s)**: Thể hiện lưu lượng mạng vào/ra biến thiên theo từng giây.
  3. **Hàng 3 (Phía dưới):**
     * Panel **Average CPU by Server**: Biểu đồ cột giúp nhận diện trực quan máy chủ đang chịu tải cao nhất.
     * Panel **Recent Server Metrics Table**: Bảng trích xuất chi tiết dữ liệu thô gần nhất.
* **Lời thoại diễn thuyết:**
  > *"Cuối cùng, em kính mời Thầy/Cô quan sát giao diện Grafana Dashboard kết nối trực tiếp với InfluxDB 3 qua giao thức chuẩn mở Apache Arrow Flight SQL trên nền gRPC.*  
  > *Như Thầy/Cô có thể thấy trên màn hình:  
  > Ở phía trên, tổng số bản ghi Total Records đã cập nhật tức thời theo luồng dữ liệu vừa gửi.  
  > Ở chính giữa, biểu đồ đường CPU Usage Over Time hiển thị 10 đường tín hiệu tương ứng 10 máy chủ, tự động vẽ lại mỗi 5 giây mà không làm gián đoạn hệ thống.  
  > Khác với các hệ thống truyền thống sử dụng HTTP REST với chi phí tuần tự hóa JSON rất lớn, Grafana ở đây nhận dữ liệu dạng mảng cột Arrow RecordBatch nguyên bản, giúp việc vẽ biểu đồ mượt mà và tiết kiệm tối đa CPU."*

---

### BƯỚC 5: TỔNG KẾT & KẾT THÚC DEMO (3:30 – 4:00)

* **Lời thoại diễn thuyết:**
  > *"Như vậy, chỉ trong vòng hơn 3 phút, mô hình thực nghiệm Proof-of-Concept đã vận hành hoàn chỉnh toàn bộ pipeline chuỗi thời gian: từ tiếp nhận telemetry tần suất cao qua Line Protocol, lưu trữ bộ nhớ và WAL an toàn, xử lý phân tích SQL vector hóa bằng DataFusion, đến trực quan hóa thời gian thực trên Grafana qua Flight SQL.*  
  > *Phần trình diễn thực nghiệm của nhóm em xin được khép lại tại đây. Em xin chân thành cảm ơn quý Thầy/Cô và sẵn sàng tiếp nhận các câu hỏi phản biện từ Hội đồng!"*

---

## 4. BẢNG XỬ LÝ SỰ CỐ KHẨN CẤP (QUICK FIX CHEATSHEET)

| Tình huống sự cố | Nguyên nhân khả dĩ | Thao tác khắc phục trong 10 giây |
| :--- | :--- | :--- |
| **Docker chưa chạy** | Quên bật Docker Desktop | Mở nhanh Docker Desktop từ Start Menu, đợi biểu tượng cá voi xanh hiện lên, chạy: `docker compose up -d`. |
| **Generator báo lỗi SSL Certificate** | Python chưa nhận diện chứng chỉ tự ký | Kiểm tra file `.env`, đảm bảo có `INFLUXDB_URL=https://localhost:8181` và script chạy với `verify_ssl=False` trong chế độ development. |
| **Grafana Dashboard không cập nhật** | Dải thời gian hiển thị bị lệch | Nhấp vào góc trên bên phải Grafana, chọn lại **`Last 5 minutes`**, sau đó nhấn phím tắt **`d` rồi `r`** trên bàn phím để ép tải lại (Force Refresh). |
| **Grafana báo lỗi `Datasource error`** | Token cấu hình bị sai lệch | Vào menu bánh răng (Administration) ➔ **Data Sources** ➔ Click vào `InfluxDB 3 Core` ➔ Cuộn xuống bấm nút xanh **Save & test** để xác nhận kết nối xanh lá. |

---

## 5. BẢNG LỆNH COPY-PASTE NHANH DÀNH CHO DIỄN GIẢ (ONE-PAGE CHEATSHEET)

Khi đứng trước Hội đồng, bạn chỉ cần mở file này và copy từng lệnh dưới đây:

```powershell
# 1. Kiểm tra trạng thái container
docker compose ps

# 2. Phát sinh 15 đợt telemetry (150 điểm đo)
python python/generator.py --interval 1.0 --iterations 15

# 3. Lấy 5 bản ghi mới nhất
docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT time, host, region, cpu_usage, memory_usage FROM server_metrics ORDER BY time DESC LIMIT 5;"

# 4. Thống kê CPU trung bình theo máy chủ
docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT host, round(avg(cpu_usage), 2) AS avg_cpu, max(cpu_usage) AS max_cpu, count(*) AS total_points FROM server_metrics GROUP BY host ORDER BY avg_cpu DESC;"

# 5. Phân nhóm thời gian DATE_BIN 5s
docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT date_bin(INTERVAL '5 seconds', time, TIMESTAMP '1970-01-01 00:00:00Z') AS bucket, round(avg(cpu_usage), 2) AS avg_cpu FROM server_metrics GROUP BY bucket ORDER BY bucket ASC;"
```

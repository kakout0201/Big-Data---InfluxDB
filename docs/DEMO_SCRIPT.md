# KỊCH BẢN TRÌNH BÀY & LIVE DEMO INFLUXDB 3

**Học phần:** Dữ liệu lớn (Big Data) — Báo cáo cơ sở lý thuyết đồ án môn học  
**Đề tài:** Nghiên cứu InfluxDB 3 và Xây dựng Hệ thống Giám sát Dữ liệu Chuỗi Thời gian  
**Sinh viên thực hiện:** Vạn Trung Tính  
**Thời lượng mục tiêu:** **3 – 4 phút**  

---

## 1. MỤC TIÊU DEMO

* **Chứng minh dữ liệu telemetry được sinh và nạp thành công** vào InfluxDB 3 qua HTTP Line Protocol.
* **Chứng minh dữ liệu có thể truy vấn và phân tích tức thời bằng SQL** thông qua engine vector hóa Apache DataFusion.
* **Chứng minh kết quả được trực quan hóa gần thời gian thực** trên Grafana thông qua giao thức chuẩn mở Apache Arrow Flight SQL.

> **Luồng kiến trúc xuyên suốt:**  
> `Python Generator` ➔ *(Line Protocol)* ➔ `InfluxDB 3 (Arrow Write Buffer & WAL)` ➔ *(SQL / DataFusion)* ➔ `Kết quả phân tích` ➔ *(Flight SQL)* ➔ `Grafana Dashboard`.

---

## 2. KỊCH BẢN NÓI & THAO TÁC CHI TIẾT (8 BƯỚC)

---

### BƯỚC 1 – GIỚI THIỆU PHẦN DEMO (≈ 15 giây)

* **Vị trí thao tác:** Đứng trước màn hình, chuẩn bị sẵn 2 cửa sổ Terminal và 1 cửa sổ trình duyệt Web Grafana.
* **🗣️ Lời nói của diễn giả:**  
  > *"Tiếp theo, em xin phép được trình bày phần demo minh họa hệ thống InfluxDB 3. Trong phần demo này, em sẽ mô phỏng luồng dữ liệu telemetry của 10 máy chủ, sau đó thực hiện ghi dữ liệu vào InfluxDB 3, truy vấn và phân tích trực tiếp bằng câu lệnh SQL tiêu chuẩn, và cuối cùng là trực quan hóa toàn bộ chỉ số trên Grafana Dashboard."*
* **Thao tác:** Chuyển nhanh sang cửa sổ **Terminal 1 (PowerShell)**.

---

### BƯỚC 2 – KIỂM TRA TRẠNG THÁI HỆ THỐNG (≈ 10 giây)

* **Vị trí thao tác:** Terminal 1
* **💻 Lệnh chạy:**
  ```powershell
  docker compose ps
  ```
* **Màn hình hiển thị mong đợi:** Thấy 2 container `influxdb3-core` và `grafana` đều ở trạng thái `Up`.
* **🗣️ Lời nói của diễn giả:**  
  > *"Đầu tiên, em kiểm tra các thành phần của hệ thống. Toàn bộ hạ tầng gồm InfluxDB 3 Core và Grafana đang được triển khai bằng Docker và hiện tại cả hai container đều đang ở trạng thái hoạt động bình thường."*

---

### BƯỚC 3 – SINH VÀ GHI DỮ LIỆU TELEMETRY (≈ 30 – 40 giây)

* **Vị trí thao tác:** Terminal 1
* **💻 Lệnh chạy:** (Phát sinh 15 đợt telemetry, mỗi đợt 1 giây)
  ```powershell
  python python/generator.py --interval 1.0 --iterations 15
  ```
* **Màn hình hiển thị mong đợi:** Terminal in ra các dòng log xác nhận kết nối và từng batch 10 server được nạp thành công:
  ```text
  [INFO] Connecting to InfluxDB 3 Core (URL: https://localhost:8181)
  [INFO] Target Database: server_monitoring
  [INFO] Iteration 1/15 — wrote 10 points (timestamp: ...)
  ...
  [INFO] Iteration 15/15 — wrote 10 points (timestamp: ...)
  ```
* **🗣️ Lời nói của diễn giả:**  
  > *"Ở bước này, module Python Generator bắt đầu mô phỏng dữ liệu telemetry từ 10 máy chủ phân bố trên 3 miền. Mỗi bản ghi gồm tọa độ timestamp nano-giây, các thông tin nhận diện Tag như host và region, cùng các trường đo lường Field như CPU, RAM, Network và Error Rate.*  
  > *Dữ liệu được nạp vào InfluxDB 3 thông qua định dạng Line Protocol siêu nhẹ.*  
  > *Nếu đối chiếu với cơ sở lý thuyết kiến trúc, dữ liệu sau khi tiếp nhận sẽ được nạp ngay vào Write Buffer trong RAM dưới dạng mảng Apache Arrow để sẵn sàng truy vấn, đồng thời được ghi tuần tự vào nhật ký WAL trên đĩa để đảm bảo an toàn tuyệt đối chống mất điện."*  
  *(Lưu ý: Không cần cố mở file WAL hay Parquet trên sân khấu).*

---

### BƯỚC 4 – KIỂM TRA DỮ LIỆU VỪA NẠP BẰNG SQL (≈ 30 giây)

* **Vị trí thao tác:** Chuyển sang **Terminal 2 (PowerShell)**
* **💻 Lệnh chạy:** *(Tránh gõ SELECT trực tiếp vào PowerShell; phải bọc qua docker exec)*
  ```powershell
  docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT time, host, region, cpu_usage, memory_usage FROM server_metrics ORDER BY time DESC LIMIT 10;"
  ```
* **Màn hình hiển thị mong đợi:** Bảng dữ liệu 10 dòng hiển thị ngay lập tức với timestamp mới nhất.
* **🗣️ Lời nói của diễn giả:**  
  > *"Kết quả trên màn hình cho thấy: dữ liệu telemetry vừa được Python phát sinh đã lập tức được ghi nhận trong bảng `server_metrics` của InfluxDB 3.*  
  > *Ở đây Thầy/Cô có thể quan sát rõ: timestamp chính xác đến nano-giây, các thông tin phân loại Tag như host, region, cùng các field đo lường thực tế. Dữ liệu nằm trong Write Buffer của RAM nên có thể truy vấn ngay tức thì mà không cần chờ đợi."*

---

### BƯỚC 5 – PHÂN TÍCH TỔNG HỢP BẰNG SQL (≈ 40 – 50 giây)

* **Vị trí thao tác:** Terminal 2
* **💻 Lệnh chạy:** (Nhóm theo Host, tính CPU trung bình và đỉnh điểm)
  ```powershell
  docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT host, round(avg(cpu_usage), 2) AS avg_cpu, max(cpu_usage) AS max_cpu FROM server_metrics GROUP BY host ORDER BY avg_cpu DESC;"
  ```
* **Màn hình hiển thị mong đợi:** Bảng xếp hạng phụ tải của 10 server từ cao xuống thấp.
* **🗣️ Lời nói của diễn giả:**  
  > *"Tiếp theo, em thực hiện một phép phân tích tổng hợp bằng SQL: nhóm dữ liệu theo từng máy chủ và tính CPU trung bình cùng CPU cao nhất để đánh giá tải hệ thống.*  
  > *Trong InfluxDB 3, câu truy vấn SQL này được tối ưu hóa và thực thi trực tiếp thông qua Apache DataFusion bằng các tập lệnh vector hóa SIMD, tính toán trực tiếp trên mảng cột Arrow trong bộ nhớ với tốc độ mili-giây."*

---

### BƯỚC 6 – PHÂN TÍCH CỬA SỔ THỜI GIAN / TIME-WINDOW (TÙY CHỌN, ≈ 30 giây)

* **Vị trí thao tác:** Terminal 2  
* **💻 Lệnh chạy:** *(Sử dụng hàm chuẩn DATE_BIN hạ mẫu dữ liệu 5 giây)*
  ```powershell
  docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT date_bin(INTERVAL '5 seconds', time, TIMESTAMP '1970-01-01 00:00:00Z') AS bucket, round(avg(cpu_usage), 2) AS avg_cpu FROM server_metrics GROUP BY bucket ORDER BY bucket DESC LIMIT 5;"
  ```
  *(Hoặc lọc 5 phút gần nhất nếu vừa nạp: `SELECT round(avg(cpu_usage), 2) AS avg_cpu FROM server_metrics WHERE time >= now() - INTERVAL '5 minutes';`)*
* **Màn hình hiển thị mong đợi:** Bảng chia khung thời gian đều đặn 5 giây (`bucket`) kèm giá trị `avg_cpu`.
* **🗣️ Lời nói của diễn giả:**  
  > *"Ngoài việc nhóm theo máy chủ, dữ liệu chuỗi thời gian còn thường xuyên được phân tích theo các khung cửa sổ thời gian cố định. Ở đây em sử dụng hàm chuyên dụng `date_bin` để chia dòng dữ liệu thành các khối 5 giây và tính CPU trung bình. Đây chính là kỹ thuật hạ mẫu (downsampling) nền tảng giúp hệ thống vẽ biểu đồ đường theo thời gian thực."*

---

### BƯỚC 7 – TRỰC QUAN HÓA TRÊN GRAFANA DASHBOARD (≈ 40 – 50 giây)

* **Vị trí thao tác:** Chuyển sang **Trình duyệt Web (Cửa sổ 3)** đang mở Dashboard: `http://localhost:3000`
* **Thao tác chuột:**  
  1. Trỏ vào widget **Total Records** (số bản ghi vừa tăng lên).
  2. Trỏ vào đồ thị **CPU Usage Over Time** (10 đường màu sắc tương ứng 10 máy chủ).
  3. Thao tác thử dropdown bộ lọc **Host** hoặc **Region** ở góc trên bên trái.
* **🗣️ Lời nói của diễn giả:**  
  > *"Cuối cùng, em sử dụng Grafana để trực quan hóa dữ liệu từ InfluxDB 3 thông qua kết nối Apache Arrow Flight SQL.*  
  > *Biểu đồ đường ở trung tâm thể hiện sự biến thiên liên tục của CPU theo thời gian thực của 10 server. Widget Total Records phía trên hiển thị số lượng bản ghi được cộng dồn tức thì. Bảng số liệu bên dưới cho phép quan sát chi tiết từng máy chủ, và kỹ sư vận hành có thể nhanh chóng lọc dữ liệu theo Region hoặc Host qua các biến lọc ở thanh điều hướng.*  
  > *Nhờ truyền tải mảng Arrow nguyên bản qua gRPC, Grafana vẽ lại đồ thị mượt mà mà không gây nghẽn băng thông."*  
  *(Lưu ý: Mở dashboard đã chuẩn bị sẵn, tuyệt đối không tạo mới hay cấu hình datasource trên sân khấu).*

---

### BƯỚC 8 – TỔNG KẾT & KẾT THÚC DEMO (≈ 15 giây)

* **🗣️ Lời nói của diễn giả:**  
  > *"Qua phần demo thực nghiệm, em đã minh họa hoàn chỉnh toàn bộ luồng xử lý của hệ thống: từ phát sinh telemetry bằng Python, ghi dữ liệu vào InfluxDB 3 qua Line Protocol, truy vấn và phân tích bằng DataFusion SQL, đến trực quan hóa kết quả trên Grafana qua Flight SQL. Đây chính là pipeline thực chứng cho các cơ sở lý thuyết đã báo cáo.*  
  > *Em xin kết thúc phần demo tại đây và chuyển sang slide kết luận của bài báo cáo!"*
* **Thao tác:** Chuyển màn hình về slide kết luận của bài thuyết trình.

---

## 3. 🧠 6 CÂU "THẦN CHÚ" CẦN NHỚ KHI NÓI

1. **Python mô phỏng dữ liệu telemetry** và gửi vào InfluxDB 3.
2. Dữ liệu được nạp vào InfluxDB 3 thông qua **giao thức Line Protocol**.
3. Em truy vấn bảng `server_metrics` để **xác nhận dữ liệu mới đã được ghi nhận tức thì trong RAM**.
4. Em sử dụng SQL tiêu chuẩn để phân tích dữ liệu, ví dụ **tính CPU trung bình nhóm theo từng host**.
5. Trong InfluxDB 3, câu truy vấn SQL được tối ưu hóa và thực thi bởi **Apache DataFusion**.
6. **Grafana trực quan hóa dữ liệu qua Arrow Flight SQL** để theo dõi các chỉ số biến thiên theo thời gian thực.

---

## 4. 🏛️ ĐỐI CHIẾU THÀNH PHẦN KIẾN TRÚC & VAI TRÒ

| Thành phần kỹ thuật | Vai trò trong hệ thống InfluxDB 3 |
| :--- | :--- |
| **Write Buffer (RAM)** | Lưu trữ dữ liệu mới nạp dưới dạng mảng Arrow để phục vụ truy vấn tức thì (**Queryable Data**). |
| **WAL (Write-Ahead Log)** | Ghi nhật ký tuần tự ra đĩa bảo đảm tính bền vững (**Durability**) và hỗ trợ phục hồi khi mất điện (**Crash Recovery**). |
| **Apache Arrow** | Biểu diễn dữ liệu dạng cột trực tiếp trong bộ nhớ RAM, hỗ trợ tính toán vector hóa SIMD. |
| **Apache Parquet** | Định dạng lưu trữ dữ liệu dạng cột chuẩn mở trên đĩa phân tích lâu dài, nén sâu. |
| **Apache DataFusion** | Query Engine hiện đại viết bằng Rust, chịu trách nhiệm thực thi SQL vector hóa. |
| **Grafana** | Nền tảng trực quan hóa, kết nối InfluxDB 3 bằng plugin Apache Arrow Flight SQL (gRPC). |

---

## 5. 🚫 NHỮNG ĐIỀU TUYỆT ĐỐI KHÔNG LÀM TRÊN SÂN KHẤU

* ❌ **Không benchmark tải lớn (100K records) trực tiếp:** Tốn thời gian và có thể làm lag máy báo cáo.
* ❌ **Không so sánh InfluxDB với MySQL:** Nếu không chuẩn bị trước môi trường benchmark đối đầu công bằng.
* ❌ **Không cố mở thư mục đĩa để soi tệp WAL hay Parquet:** Compactor chạy nền không đồng bộ, không cần thiết chứng minh trên sân khấu.
* ❌ **Không chạy quá nhiều câu SQL lan man:** Chỉ chạy đúng 2 câu then chốt: 1 câu xem dữ liệu mới nạp và 1 câu `GROUP BY host`.
* ❌ **Không cài đặt package hay cấu hình lại Docker trên sân khấu.**
* ❌ **Không đưa mật khẩu, token hay API key lên màn hình trình chiếu.**

---

## 6. ✅ CHECKLIST KIỂM TRA TRƯỚC GIỜ G

- [ ] Docker Desktop đang chạy, container `influxdb3-core` và `grafana` hiển thị trạng thái `Up`.
- [ ] Script `generator.py` chạy thử thành công 1 batch.
- [ ] Bảng `server_metrics` đã có dữ liệu.
- [ ] Đã chạy thử lệnh `docker exec ... SELECT` xem kết quả in ra đúng bảng.
- [ ] Grafana Dashboard mở sẵn tại `localhost:3000`, hiển thị đủ 12 panels.
- [ ] Cài đặt Grafana: Time range = **Last 5 minutes**, Refresh = **5s**.
- [ ] Đã mở sẵn 2 cửa sổ PowerShell và 1 cửa sổ trình duyệt Web.
- [ ] **Phương án dự phòng:** Nếu live demo gặp sự cố mạng/máy treo, bình tĩnh chuyển sang ảnh chụp màn hình Dashboard (có sẵn trong slide báo cáo) và thuyết minh tiếp.

---

## 7. 🗺️ SƠ ĐỒ NHỚ NHANH (QUICK MINDMAP)

```text
Python Generator (10 servers, 3 regions)
       │
       ▼ [Line Protocol qua HTTP]
InfluxDB 3 Core
       ├── RAM: Write Buffer (Apache Arrow) ➔ [Queryable Data tức thì]
       ├── Đĩa ngắn hạn: WAL (Write-Ahead Log) ➔ [Durability chống mất điện]
       └── Đĩa dài hạn: Apache Parquet (Compactor nén nền)
       │
       ▼ [DataFusion SQL Engine (SIMD Vectorized Execution)]
Kết quả phân tích (SELECT / GROUP BY / DATE_BIN)
       │
       ▼ [Apache Arrow Flight SQL qua gRPC]
Grafana Dashboard (Trực quan hóa thời gian thực)
```

---

## 8. 📄 BẢNG LỆNH COPY-PASTE NHANH DÀNH CHO DIỄN GIẢ

*(Mở sẵn bảng này ở cửa sổ phụ, chỉ cần copy từng dòng dán vào terminal):*

```powershell
# BƯỚC 2: Kiểm tra trạng thái hệ thống
docker compose ps

# BƯỚC 3: Phát sinh 15 đợt telemetry (150 điểm đo)
python python/generator.py --interval 1.0 --iterations 15

# BƯỚC 4: Kiểm tra 10 bản ghi mới nhất vừa nạp
docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT time, host, region, cpu_usage, memory_usage FROM server_metrics ORDER BY time DESC LIMIT 10;"

# BƯỚC 5: Phân tích CPU trung bình theo máy chủ (GROUP BY host)
docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT host, round(avg(cpu_usage), 2) AS avg_cpu, max(cpu_usage) AS max_cpu FROM server_metrics GROUP BY host ORDER BY avg_cpu DESC;"

# BƯỚC 6 (Tùy chọn): Phân tích hạ mẫu theo khung 5 giây (DATE_BIN)
docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT date_bin(INTERVAL '5 seconds', time, TIMESTAMP '1970-01-01 00:00:00Z') AS bucket, round(avg(cpu_usage), 2) AS avg_cpu FROM server_metrics GROUP BY bucket ORDER BY bucket DESC LIMIT 5;"
```

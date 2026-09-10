# KỊCH BẢN TRÌNH DIỄN HỆ THỐNG TRỰC TIẾP (LIVE DEMO SCRIPT)

**Học phần:** Dữ liệu lớn (Big Data)  
**Đề tài:** Nghiên cứu InfluxDB 3 và xây dựng hệ thống giám sát dữ liệu chuỗi thời gian thời gian thực  
**Thời lượng thực hiện:** 3 – 4 phút (Khuyến nghị: 3 phút 30 giây)  
**Mục tiêu:** Chứng minh năng lực của prototype trong việc thu thập telemetry, lưu trữ chuỗi thời gian vào InfluxDB 3 Core, thực thi phân tích dữ liệu bằng SQL chuẩn (DataFusion) và hiển thị trực quan hóa trên Grafana Dashboard.  
**Nguyên tắc vàng:** Không phô trương tính năng thừa, không tuyên bố độ trễ demo "dưới 50ms" (chỉ viện dẫn số liệu benchmark khi được hỏi).

---

## 1. CHUẨN BỊ TRƯỚC BUỔI THUYẾT TRÌNH (PRE-DEMO SETUP)

Trước khi bắt đầu bài thuyết trình, chuẩn bị sẵn 3 cửa sổ màn hình:
1. **Cửa sổ 1 (Terminal 1):** Nằm tại thư mục dự án `D:\Kỳ 1 năm 4\Big Data\INFLUXDB`. Môi trường ảo `.venv` đã kích hoạt.
2. **Cửa sổ 2 (Terminal 2):** Nằm tại cùng thư mục, sẵn sàng thực thi lệnh CLI hoặc script truy vấn.
3. **Cửa sổ 3 (Trình duyệt Web):** Mở sẵn tab [http://localhost:3000](http://localhost:3000), đã đăng nhập tài khoản Grafana, mở sẵn dashboard:  
   `http://localhost:3000/d/server_monitoring_influxdb3/server-monitoring-e28094-influxdb-3` (chọn khoảng thời gian hiển thị: *Last 5 minutes*, tự động làm mới: *5s*).

---

## 2. TIẾN TRÌNH THAO TÁC TỪNG BƯỚC (STEP-BY-STEP WORKFLOW)

---

### BƯỚC 1: KIỂM TRA MÔI TRƯỜNG DOCKER (0:00 – 0:30)

* **Thao tác:** Trên Terminal 1, chạy lệnh kiểm tra trạng thái các container:
  ```powershell
  docker compose ps
  ```
* **Kết quả hiển thị mong đợi:**  
  Cả 2 dịch vụ đều ở trạng thái `running` (Up):
  * `influxdb3-core` (cổng `8181/tcp`)
  * `grafana` (cổng `3000/tcp`)
* **Lời thoại của diễn giả:**  
  > *"Kính thưa Thầy/Cô, đầu tiên em kiểm tra trạng thái hạ tầng thực nghiệm. Hệ thống gồm 2 container Docker: InfluxDB 3 Core đóng vai trò TSDB engine và Grafana 11.5 đóng vai trò tầng trực quan hóa. Cả hai đều đang vận hành bình thường."*

---

### BƯỚC 2: KHỞI ĐỘNG PYTHON TELEMETRY GENERATOR (0:30 – 1:15)

* **Thao tác:** Trên Terminal 1, khởi động script phát sinh dữ liệu telemetry theo thời gian thực (chạy 15 batch liên tiếp, mỗi batch cách nhau 1 giây):
  ```powershell
  python python/generator.py --interval 1.0 --iterations 15
  ```
* **Kết quả hiển thị mong đợi:**  
  Terminal in ra các dòng log xác nhận kết nối và từng batch được gửi thành công:
  ```text
  [INFO] Connecting to InfluxDB 3 Core (URL: http://localhost:8181)
  [INFO] Target Database: server_monitoring
  [INFO] Servers: 10 across 3 regions (hcm, hanoi, danang)
  [INFO] Iteration 1/15 — wrote 10 points (timestamp: 2026-09-05T...)
  [INFO] Iteration 2/15 — wrote 10 points (timestamp: 2026-09-05T...)
  ...
  ```
* **Lời thoại của diễn giả:**  
  > *"Em tiến hành chạy module Python Telemetry Generator. Script này mô phỏng 10 máy chủ phân bố trên 3 khu vực địa lý: HCM, Hà Nội và Đà Nẵng. Mỗi giây, 10 điểm đo bao gồm CPU, Memory, Network và Error Rate được đóng gói theo chuẩn Line Protocol và gửi đồng thời tới InfluxDB 3 Core qua HTTP API."*

---

### BƯỚC 3: TRUY VẤN DỮ LIỆU GẦN NHẤT BẰNG SQL (1:15 – 1:50)

* **Thao tác:** Trên Terminal 2, thực thi câu lệnh SQL trích xuất 10 bản ghi mới nhất vừa được nạp:
  ```powershell
  docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT time, host, region, cpu_usage, memory_usage FROM server_metrics ORDER BY time DESC LIMIT 10;"
  ```
* **Kết quả hiển thị mong đợi:**  
  Bảng kết quả hiển thị 10 dòng dữ liệu kèm timestamp nano-giây vừa được sinh ra ở Bước 2.
* **Lời thoại của diễn giả:**  
  > *"Ngay lập tức, em thực thi câu lệnh SQL tiêu chuẩn để kiểm tra dữ liệu vừa nạp. Nhờ kiến trúc In-Memory Arrow Buffer của InfluxDB 3, dữ liệu vừa gửi đến có thể được truy vấn ngay lập tức mà không cần phải chờ đợi quá trình nén hay ghi đĩa hoàn tất."*

---

### BƯỚC 4: THỰC THI TRUY VẤN TỔNG HỢP THEO MÁY CHỦ (1:50 – 2:30)

* **Thao tác:** Trên Terminal 2, thực thi câu lệnh SQL gom nhóm và tính toán tổng hợp trên Tag dimension `host`:
  ```powershell
  docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT host, round(avg(cpu_usage), 2) AS avg_cpu, max(cpu_usage) AS max_cpu, count(*) AS total_points FROM server_metrics GROUP BY host ORDER BY avg_cpu DESC;"
  ```
* **Kết quả hiển thị mong đợi:**  
  Bảng 10 dòng hiển thị đúng 10 node `server-01` đến `server-10`, sắp xếp giảm dần theo mức CPU trung bình.
* **Lời thoại của diễn giả:**  
  > *"Tiếp theo là câu lệnh phân tích tổng hợp: tính CPU trung bình, CPU đỉnh điểm và tổng số điểm đo của từng máy chủ. Engine Apache DataFusion thực thi phân tích vector hóa song song trên các cột số trong bộ nhớ và trả về kết quả xếp hạng tải giữa các máy chủ ngay tức thì."*

---

### BƯỚC 5: TRUY VẤN PHÂN BỔ THỜI GIAN VỚI DATE_BIN (2:30 – 3:00)

* **Thao tác:** Trên Terminal 2, thực thi câu truy vấn thời gian thực sử dụng hàm `date_bin` gom nhóm theo cửa sổ 5 giây:
  ```powershell
  docker exec -i influxdb3-core influxdb3 query --database server_monitoring "SELECT date_bin(INTERVAL '5 seconds', time, TIMESTAMP '1970-01-01 00:00:00Z') AS time_bucket, round(avg(cpu_usage), 2) AS avg_cpu FROM server_metrics GROUP BY time_bucket ORDER BY time_bucket ASC;"
  ```
* **Kết quả hiển thị mong đợi:**  
  Danh sách các khung thời gian 5 giây (`time_bucket`) kèm giá trị `avg_cpu` biến thiên tương ứng.
* **Lời thoại của diễn giả:**  
  > *"Để phục vụ bài toán vẽ biểu đồ xu hướng dài hạn (downsampling), em sử dụng hàm chuyên dụng `date_bin` của DataFusion SQL. Hàm này tự động chia trục thời gian thành các khung đều đặn 5 giây và tính mức CPU trung bình cho mỗi khung. Đây chính là kỹ thuật nền tảng để tạo các biểu đồ trực quan hóa."*

---

### BƯỚC 6: TRỰC QUAN HÓA TRÊN GRAFANA DASHBOARD (3:00 – 3:40)

* **Thao tác:** Diễn giả chuyển sang cửa sổ trình duyệt Web đang mở Dashboard Grafana `Server Monitoring — InfluxDB 3`. Chỉ chuột vào 3 vùng trọng tâm:
  1. **Hàng 1 (Góc trên):** Widget **Total Records** (con số đang tăng lên theo dữ liệu vừa nạp) và **Average CPU Usage** (đồng hồ Gauge màu vàng/xanh).
  2. **Hàng 2 (Chính giữa):** Panel **CPU Usage Over Time** (biểu đồ đường phân tách 10 series màu sắc khác nhau của 10 server).
  3. **Hàng 3 (Phía dưới):** Panel **Average CPU by Server** (biểu đồ cột so sánh mức tải giữa các server).
* **Lời thoại của diễn giả:**  
  > *"Cuối cùng, em mở giao diện Grafana Dashboard tại cổng 3000. Grafana kết nối trực tiếp với InfluxDB 3 qua chuẩn Arrow Flight SQL.  
  > Như Thầy/Cô có thể thấy:  
  > Ở hàng trên cùng, widget Total Records vừa cập nhật theo các điểm đo mà script Python vừa gửi.  
  > Ở giữa là biểu đồ chuỗi thời gian CPU Usage Over Time: các đường tín hiệu của 10 máy chủ liên tục cập nhật theo thời gian thực.  
  > Và ở bên dưới, biểu đồ cột Average CPU by Server giúp kỹ sư vận hành lập tức phát hiện máy chủ nào đang chịu tải lớn nhất trong hệ thống.  
  > Toàn bộ pipeline từ Ingestion $\to$ TSDB Storage $\to$ DataFusion SQL $\to$ Grafana đã vận hành trơn tru và nhất quán."*

---

## 3. PHÒNG NGỪA RỦI RO & XỬ LÝ SỰ CỐ (TROUBLESHOOTING CONTINGENCY)

| Sự cố tiềm ẩn | Nguyên nhân | Biện pháp xử lý ngay lập tức |
|:---|:---|:---|
| Docker container chưa chạy | Quên khởi động trước buổi báo cáo | Chạy nhanh lệnh: `docker compose up -d` (mất ~5 giây). |
| Generator báo lỗi kết nối `8181` | Container InfluxDB đang khởi động lại | Chờ 3 giây, kiểm tra `docker compose ps`, chạy lại lệnh `generator.py`. |
| Grafana báo lỗi `Datasource error` | Token trong `.env` chưa được nạp | Vào mục Administration $\to$ Data Sources $\to$ Click "Save & test" lại datasource `InfluxDB 3 Core`. |
| Màn hình Grafana không tự cập nhật | Đang ở chế độ dừng (Pause) | Bấm phím tắt `d r` trên bàn phím hoặc chỉnh thanh Refresh sang `5s`. |

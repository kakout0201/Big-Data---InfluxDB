---
name: weather-timeseries-development
description: Quy trình phát triển đồ án dữ liệu thời tiết chuỗi thời gian trên InfluxDB 3 trong repository này. Dùng khi chọn hoặc khảo sát nguồn dữ liệu thời tiết, viết collector, làm sạch dữ liệu, thiết kế schema tag/field, viết SQL phân tích, chọn hoặc implement phương pháp phát hiện bất thường, làm dashboard Grafana, hoặc đánh giá và kiểm thử pipeline weather.
---

# Weather Time-Series Development

Skill này mô tả **cách làm việc** cho đồ án. Các sự thật về repository (cấu trúc, lệnh, cấu hình, phase hiện tại) nằm trong `CLAUDE.md`. Đọc mục "Current Development Phase" ở đó trước khi bắt đầu.

## Nguyên tắc cốt lõi

- InfluxDB 3 Core là database chính; Python là ngôn ngữ xử lý chính; thời tiết là domain chính.
- Tôn trọng thiết kế time-series: tag, field và timestamp phải được chọn có chủ đích.
- Timestamp phải được bảo toàn đúng: là thời điểm đo, đã chuyển về UTC.
- Làm sạch dữ liệu trước khi ghi khi phù hợp.
- Anomaly detection phải giải thích được; tránh độ phức tạp ML không cần thiết.
- Không thêm hạ tầng không cần thiết.
- Bảo toàn các thành phần đang hoạt động.
- Test trước khi tuyên bố hoàn thành.
- Thứ tự ưu tiên: Simple → Correct → Testable → Explainable → Demoable.
## Git Workflow
- Sau khi hoàn thành một task và kiểm tra test pass:
  1. KHÔNG tự ý chạy `git commit`.
  2. Hãy tóm tắt ngắn gọn các file đã thay đổi.
  3. Đề xuất sẵn một câu lệnh git commit chuẩn Conventional Commits (ví dụ: `git commit -m "feat(collector): implement open-meteo hourly fetcher"`).
  4. Hỏi người dùng: "Task đã hoàn thành và test pass, bạn có muốn tôi commit thay đổi này không?"

## 1. Khảo sát nguồn dữ liệu (trước mọi thiết kế)

Không thiết kế schema từ trí nhớ hay giả định. Lấy một mẫu dữ liệu thật rồi ghi lại:
- danh sách trường, kiểu dữ liệu và **đơn vị** (°C/°F, hPa, m/s/km/h, mm);
- **timezone** của timestamp gốc và độ phân giải (giờ, 10 phút, ...);
- tần suất mẫu, khoảng thời gian có sẵn, giới hạn request và giấy phép;
- cách nguồn biểu diễn giá trị thiếu (null, rỗng, `-999`, ...);
- số địa điểm/trạm và thông tin định danh chúng.

Trình bày kết quả khảo sát cho người dùng trước khi chốt schema.

## 2. Thiết kế schema InfluxDB

Với mỗi cột của nguồn, tự hỏi:

| Câu hỏi | Nếu "có" |
|---|---|
| Nó định danh *ai/ở đâu* đo, và dùng để lọc/nhóm? | **Tag** (chuỗi, cardinality thấp) |
| Nó là giá trị đo thay đổi theo thời gian? | **Field** (kiểu cố định, ghi rõ đơn vị) |
| Nó là thời điểm đo? | **Timestamp** (UTC, ns) |

- Không đưa giá trị liên tục (nhiệt độ, tọa độ dạng số) vào tag.
- Không đưa giá trị có cardinality không giới hạn (ID request, chuỗi ngẫu nhiên) vào tag.
- Đặt tên field theo snake_case, có thể kèm đơn vị khi dễ nhầm (ví dụ `temperature_c`). Chốt quy ước một lần rồi giữ nhất quán.
- Mỗi field giữ một kiểu duy nhất (float cho số đo, kể cả khi giá trị trông như số nguyên).
- Ghi schema đã chốt vào mục "Data Model" của `CLAUDE.md`.

## 3. Thu thập và làm sạch

- Collector là script CLI, dùng lại `python/config.py`. Tham khảo `python/generator.py` cho cách kết nối, ghi batch và log.
- Các bước làm sạch, mỗi bước một hàm thuần để test được:
  1. parse và chuẩn hóa timestamp về UTC;
  2. chuẩn hóa đơn vị;
  3. loại bản ghi trùng;
  4. đánh dấu hoặc loại giá trị thiếu theo quy tắc ghi rõ;
  5. kiểm tra miền giá trị vật lý (ví dụ độ ẩm 0–100%).
- **Phân biệt "dữ liệu hỏng" với "bất thường thật".** Giá trị không thể xảy ra về mặt vật lý hoặc lỗi định dạng thì làm sạch. Giá trị hiếm nhưng có thể xảy ra (nắng nóng, mưa lớn) phải được **giữ lại**, vì đó là đầu vào của anomaly detection.
- Ghi lại số bản ghi bị loại/sửa ở mỗi bước để đưa vào báo cáo.
- Ghi theo batch; nạp lại cùng dữ liệu phải idempotent (cùng bảng + tag + timestamp sẽ ghi đè, không nhân bản).

## 4. Phát hiện bất thường

Chỉ đánh giá các phương pháp: **Threshold, Z-score, IQR, Moving Average, Rolling Statistics.** Không dùng ML/DL trừ khi người dùng yêu cầu rõ ràng.

Quy trình bắt buộc, không bỏ bước:
1. **Inspect data:** xem mẫu, khoảng giá trị, tỷ lệ thiếu theo từng field và địa điểm.
2. **Analyze distribution:** histogram/phân vị, độ lệch, tính mùa vụ và chu kỳ ngày-đêm. Z-score giả định phân phối gần chuẩn; dữ liệu có chu kỳ mạnh thường cần so với baseline cục bộ (rolling) thay vì baseline toàn cục.
3. **Compare methods:** chạy các phương pháp ứng viên trên cùng dữ liệu. So sánh số điểm bị gắn cờ, các ví dụ cụ thể, độ nhạy với tham số (ngưỡng, kích thước cửa sổ) và khả năng giải thích.
4. **Select method:** trình bày so sánh cho người dùng và để người dùng quyết định. Nêu lý do chọn và hạn chế.
5. **Implement:** logic phát hiện là hàm thuần (đầu vào là chuỗi giá trị, đầu ra là cờ và điểm số), test được không cần DB. Tham số đặt ở cấu hình hoặc CLI, không hard-code rải rác.
6. **Evaluate:** kiểm tra trên các trường hợp đã biết (bất thường chèn thủ công hoặc sự kiện thời tiết có thật), báo cáo kết quả bằng số liệu.

Mỗi điểm bất thường phải trả lời được câu hỏi "tại sao điểm này bị gắn cờ?", ví dụ: "nhiệt độ lệch 3,2σ so với trung bình 24 giờ trước". Cân nhắc lưu kết quả bất thường vào một bảng riêng trong InfluxDB để Grafana hiển thị; quyết định này cần người dùng duyệt.

## 5. SQL và Grafana

- SQL theo dialect DataFusion; dùng `date_bin(...)` để gom cửa sổ thời gian (mẫu có trong `queries/03_time_series.sql`).
- Luôn lọc theo khoảng thời gian trong truy vấn dashboard (`WHERE $__timeFilter(time)`) thay vì quét toàn bảng.
- Dashboard là file JSON trong `grafana/dashboards_json/`. Datasource weather cần trỏ đúng database weather (xem mục Grafana trong `CLAUDE.md`).

## 6. Hạ tầng

Không thêm Kafka, Redis, RabbitMQ, Kubernetes, Spark, Flink, Airflow, microservices, cloud, MLflow hay service mới vào `docker-compose.yml` khi chưa được yêu cầu. Nếu thấy thật sự cần, đề xuất kèm lý do và chờ duyệt.

## 7. Checklist trước khi báo hoàn thành

- [ ] Code đã chạy thực tế (không chỉ đọc lại code).
- [ ] Hàm thuần mới có test và test đã pass.
- [ ] Dữ liệu ghi vào InfluxDB đã được đọc lại để kiểm tra: số bản ghi, min/max time, NULL, số địa điểm.
- [ ] Không có secret trong diff; biến môi trường mới đã có placeholder trong `.env.example`.
- [ ] Thành phần legacy bị thay thế đã được dọn trong cùng thay đổi.
- [ ] `CLAUDE.md` đã được cập nhật nếu schema, lệnh hoặc phase thay đổi.
- [ ] Báo cáo kết quả trung thực, kể cả phần chưa làm hoặc chưa kiểm tra.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Đồ án môn Big Data (cá nhân): **Xây dựng hệ thống lưu trữ, phân tích và phát hiện bất thường dữ liệu thời tiết chuỗi thời gian sử dụng InfluxDB 3.**

Repository này **không phải project mới**. Nó được phát triển tiếp từ project tiểu luận InfluxDB 3 (Phase 1, đã hoàn thành). Hạ tầng (Docker, TLS, InfluxDB 3 Core, Grafana provisioning, Python config) được tái sử dụng; phần domain đang chuyển từ server monitoring sang thời tiết.

Toàn bộ tài liệu của dự án viết bằng tiếng Việt.

## Project History

**Phase 1 — Tiểu luận InfluxDB 3 (ĐÃ HOÀN THÀNH, legacy).** Nghiên cứu InfluxDB 3 / Time-Series Database, demo giám sát server, các câu SQL, dashboard Grafana và benchmark (thông lượng ghi, độ trễ truy vấn, lưu trữ Parquet).
- Toàn bộ trạng thái cuối của Phase 1 được giữ ở git tag **`phase1-essay`**.
- Dữ liệu demo: database `server_monitoring`, bảng `server_metrics`; tag `host`, `region`; field `cpu_usage`, `memory_usage`, `network_in`, `network_out`, `error_rate`.
- Dữ liệu benchmark: database `benchmark_monitoring`, bảng `server_metrics_benchmark`.
- Cả hai database này vẫn còn trong Docker volume `influxdb3_data`; không xóa trừ khi được yêu cầu.

**Phase 2 — Đồ án Weather Time-Series (ĐANG PHÁT TRIỂN).** Xem các mục bên dưới.

## Current Goal

Pipeline dữ liệu thời tiết chuỗi thời gian, với **phát hiện bất thường là chức năng trọng tâm**. Ưu tiên theo thứ tự: Simple → Correct → Testable → Explainable → Demoable.

## Architecture

```text
Weather Data Source (API / dataset — chưa chọn)
        ↓
Data Collection          (Python)
        ↓
Data Cleaning / Transformation (Python, trước khi ghi)
        ↓
InfluxDB 3 Core          (HTTPS :8181, Line Protocol để ghi, SQL/DataFusion để đọc)
        ↓
SQL / Analysis
        ↓
Anomaly Detection        (Python và/hoặc SQL)
        ↓
Grafana                  (:3000, datasource InfluxDB chế độ SQL qua Flight SQL)
```

Mọi tầng đã được implement (P2–P8). Demo server monitoring của Phase 1 đã bị gỡ ở P8; lịch sử còn ở tag `phase1-essay`.

## Technology Stack

- **Database:** InfluxDB 3 Core (`influxdb:3-core`). Engine Apache Arrow + DataFusion, lưu trữ Parquet, SQL dialect DataFusion.
- **Xử lý:** Python 3.11 trong `.venv/`. Đã cài `influxdb3-python` (module `influxdb_client_3`), `python-dotenv`, `pyarrow`, `numpy`. Chưa có `requirements.txt`; khi thêm dependency mới thì tạo file này và ghi rõ phiên bản.
- **Visualization:** Grafana 11.5.2, datasource `influxdb` built-in (không dùng plugin ngoài).
- **Container:** Docker Compose (2 service: `influxdb`, `grafana`).

## Repository Structure

```text
docker-compose.yml        # InfluxDB 3 Core + Grafana
.env.example              # mẫu biến môi trường (chỉ placeholder)
certs/                    # TLS cert/key (git ignore)
python/
  config.py               # InfluxDBConfig.load(): đọc .env, dùng chung cho mọi script
  open_meteo.py           # client Open-Meteo (I/O): LOCATIONS, FIELD_MAP, EXPECTED_UNITS, retry
  weather_schema.py       # schema đã chốt: bảng, tag, field, PHYSICAL_RANGES, to_point()
  weather_cleaning.py     # P4: các bước làm sạch dạng hàm thuần + CleaningReport
  weather_collector.py    # P3: CLI backfill / recent / verify
  test_weather_cleaning.py
  run_sql.py              # P6: chạy file .sql từng câu lệnh, in bảng (+ test_run_sql.py)
  weather_anomaly.py      # P7: các detector dạng hàm thuần (numpy) + inject/metrics (+ test_weather_anomaly.py)
  evaluate_anomaly.py     # P7: so sánh các phương pháp trên dữ liệu thật (chỉ đọc DB)
  anomaly_job.py          # P7: chạy các phương pháp đã chọn, xóa rồi ghi lại bảng weather_anomalies, đối chiếu count(*)
  survey_weather_source.py  # P2: script khảo sát nguồn (chỉ đọc)
  check_dashboard.py      # P8: kiểm tra tĩnh dashboard JSON + chạy mọi truy vấn panel qua Grafana (+ test_check_dashboard.py)
queries/weather_analysis/ # P6: 5 file SQL phân tích weather (giờ VN = time + 7h), có README
grafana/
  provisioning/           # datasource influxdb3_weather + dashboard provider "Weather"
  dashboards_json/        # P8: weather_analytics.json
archive/phase1-essay/     # Đóng băng: module benchmark + báo cáo + kịch bản demo tiểu luận
.claude/skills/weather-timeseries-development/   # skill quy trình phát triển đồ án
```

- `archive/` là tài liệu tham khảo, **không bảo trì**; không sửa code trong đó. Khi đánh giá đồ án (Roadmap P9) có thể tham khảo phương pháp đo trong `archive/phase1-essay/benchmark/`: nạp dữ liệu sẵn vào bộ nhớ, chỉ bấm giờ quanh lời gọi ghi/truy vấn, kiểm tra lại `count(*)`, báo cáo trung vị. `storage_measurement.py` trong đó không phụ thuộc schema.
- Khi code weather thay thế một thành phần legacy, xóa thành phần legacy đó trong cùng thay đổi (lịch sử vẫn còn ở tag `phase1-essay`). Không tạo thư mục rỗng trước khi có code.

## InfluxDB Conventions

- InfluxDB 3 Core là database chính duy nhất. Không thêm database khác.
- Thiết kế theo mô hình time-series, không áp mô hình quan hệ một cách máy móc:
  - **Tag** = định danh / phân loại / lọc (ví dụ trạm, vị trí). Giá trị là chuỗi, số lượng giá trị khác nhau (cardinality) thấp và ổn định.
  - **Field** = giá trị đo được (nhiệt độ, độ ẩm, ...). Giữ kiểu dữ liệu nhất quán cho mỗi field; một field đã ghi là float thì không được ghi integer vào sau.
  - **Timestamp** = chiều thời gian. Dùng timestamp **của lần đo** (không phải thời điểm ghi), ở UTC, độ chính xác nanosecond.
- Trong InfluxDB 3, một điểm được định danh bởi bảng + tập tag + timestamp. Ghi lại một điểm trùng cả ba sẽ ghi đè giá trị field, nên nạp lại cùng dữ liệu là idempotent; tận dụng điều này khi nạp lại. Ngược lại, đổi tag của cùng một lần đo sẽ tạo ra điểm mới, gây trùng dữ liệu.
- Ghi theo batch: bài đo Phase 1 cho thấy batch lớn (5.000–10.000 điểm) nhanh hơn batch 500 điểm hơn 10 lần.
- Database demo legacy là `server_monitoring`; database weather là `weather`. Không ghi dữ liệu weather vào database legacy.
- Chạy SQL thủ công qua `docker exec influxdb3-core influxdb3 query ...` (xem Development Commands). Container phải giữ tên `influxdb3-core`.
- **Giới hạn của Core với dữ liệu lịch sử (đã kiểm chứng ngày 2026-10-06, InfluxDB 3 Core 3.11.2):**
  - Dữ liệu được chia theo khối thời gian `gen1-duration` (mặc định 10 phút; chỉ hỗ trợ 1m/5m/10m), và **Core không có compaction**. Vì vậy mỗi giờ lịch sử nạp bù là một khối riêng: 24.192 khối cho 2024-01 → 2026-10.
  - Khi persist, mỗi khối thành một file Parquet. `query-file-limit` mặc định là **432 file**; truy vấn nào trải dài hơn khoảng 432 giờ (~18 ngày) dữ liệu đã persist sẽ **bị lỗi**.
  - **Khi nào persist (3.11.2):** bản này **không có** `--force-snapshot-max-age`; tài liệu online mô tả phiên bản khác.
    - Snapshot chỉ chạy theo số file WAL hoặc khi thiếu bộ nhớ (`--force-snapshot-mem-size`).
    - Lịch sử snapshot cho thấy khoảng cách khoảng **1,5 × `wal-files-per-snapshot`**, tức ~900 file WAL (1812 → 2708; snapshot kế tiếp chạy đúng ở ~3608).
    - Mỗi lần ghi, nếu cách lần trước ≥ 1 giây, tạo một file WAL. Với collector chạy mỗi giờ, dữ liệu có thể nằm trong RAM/WAL nhiều tuần mà không persist.
    - Server không nhận ghi sẽ không bao giờ snapshot (đã quan sát 8 giờ không persist).
  - **Số liệu đo (2026-10-06):** 72.636 dòng, 1 warm-up + 5 lần đo, lấy trung vị, chỉ bấm giờ quanh `client.query()`. Script đo nằm ngoài repo; phương pháp giống `archive/phase1-essay/benchmark/`.

    | Truy vấn | Trong RAM (chưa persist) | Sau persist (24.012 file Parquet) |
    |---|---|---|
    | `count(*)` toàn bảng | 1,789 s | 1,330 s |
    | 7 ngày, mọi field (cửa sổ cố định từ 2026-09-28 20:00Z) | 0,015 s (504 dòng) | 0,025 s (528 dòng) |
    | Toàn lịch sử: trung bình theo ngày, Hà Nội | 2,001 s | 1,817 s |

    - Sau persist: **24.012 file**, trung bình **3 dòng và 6,2 KB mỗi file** (1 giờ × 3 location). Tổng 144 MB Parquet cho 72.036 dòng, khoảng 2 KB/dòng; thư mục `dbs/3` chiếm 286 MB trên đĩa.
    - Log truy vấn xác nhận `count(*)` đọc `parquet_files=24012`, tức với giới hạn mặc định 432 truy vấn này sẽ bị từ chối. Lỗi này suy ra từ tài liệu và số file, **chưa quan sát trực tiếp**, vì giới hạn đã được nâng trước khi persist.
    - Diễn giải:
      - Chi phí chính nằm ở số lượng phân mảnh (khoảng 24k khối/file), không nằm ở số dòng (72k dòng là nhỏ). Khi còn trong RAM, log báo `dedup ... fanout too wide`.
      - Persist không làm chậm truy vấn dài; truy vấn ngắn vẫn dưới 30 ms.
  - **Đã xử lý (người dùng duyệt):** đặt `INFLUXDB3_QUERY_FILE_LIMIT=50000` trong `docker-compose.yml`, đủ cho khoảng 5,7 năm dữ liệu theo giờ. Đổi giá trị này phải tạo lại container bằng `docker compose up -d influxdb`.
  - Đây là hạn chế của Core cần ghi trong báo cáo: Core tối ưu cho dữ liệu gần đây; bản Enterprise có compactor để gộp file.
  - Truy vấn phân tích nên luôn lọc theo khoảng thời gian để chỉ chạm vào những file cần thiết.

## Data Model

Schema **đã chốt ở P2** (2026-10-06). Định nghĩa trong code nằm ở `python/weather_schema.py`.

| Thành phần | Giá trị |
|---|---|
| Database | `weather` (đổi bằng biến `WEATHER_INFLUXDB_DATABASE` hoặc tham số `--database`) |
| Bảng | `weather_hourly` |
| Tag | `location` = `hcm` \| `hanoi` \| `danang` (khớp với 3 region của Phase 1) |
| Time | đầu giờ, UTC, độ chính xác ns. Lấy từ `timeformat=unixtime` của Open-Meteo, nên không có chuyển đổi timezone |
| Field float (9) | `temperature_c`, `humidity_pct`, `dew_point_c`, `precipitation_mm`, `pressure_msl_hpa`, `cloud_cover_pct`, `wind_speed_ms`, `wind_direction_deg`, `wind_gusts_ms` |
| Field integer | `weather_code` (mã WMO, dạng phân loại) |
| Field string | `data_source` = `forecast` \| `archive` |

Quy ước dữ liệu:
- **Lượng mưa:** `precipitation_mm` là tổng của **giờ trước đó** (theo Open-Meteo).
- **Bẫy kiểu dữ liệu:** API trả `relative_humidity_2m`, `cloud_cover`, `wind_direction_10m` dưới dạng int, nên luôn ép sang float trước khi ghi. Nếu một lần ghi int lọt vào, InfluxDB sẽ chốt kiểu cột sai và từ chối các lần ghi float sau đó.
- **Archive và forecast:** archive luôn thắng.
  - `backfill` ghi đè forecast cho cùng `(location, time)`.
  - `recent` bỏ qua mọi giờ ≤ giờ archive mới nhất của từng location.
  - Cả hai chiều đã được kiểm chứng trên database thật.
- **Giá trị thiếu (JSON `null`):** không nội suy; bỏ field đó khỏi point, đếm vào báo cáo làm sạch. Giờ nào mọi field đều null thì bỏ cả dòng.
- **Tọa độ:** tọa độ trung tâm thành phố và tọa độ ô lưới sau khi snap nằm trong `open_meteo.LOCATIONS` và output của script survey, không lưu trong InfluxDB.

**Bảng kết quả `weather_anomalies`** (P7, dữ liệu dẫn xuất; định nghĩa ở `weather_schema.py`):

| Thành phần | Giá trị |
|---|---|
| Tag | `location`; `field` (`temperature_c`, `pressure_msl_hpa`, `wind_gusts_ms`, `rain_24h_mm`); `method`; `direction` (`high`, `low`, hoặc `none` cho `stuck`) |
| Time | giờ bị gắn cờ, trùng timestamp với `weather_hourly` |
| Field float | `value` (giá trị mà phương pháp đã đánh giá: trung bình 168h với `persistent_climate_zscore`, tổng 24h với `rain_24h_mm`), `baseline`, `score`, `k` (tham số: giới hạn z, k của IQR, ngưỡng, hoặc độ dài đợt kẹt) |
| Field string | `severity` (cấp Beaufort, mức mưa 24h, mức nắng nóng 35/37/39 °C, độ mạnh của z), `reason` (câu giải thích), `detected_at` |

- Chỉ lưu các điểm bị gắn cờ.
- **Không ghi tay vào bảng này.** `anomaly_job.py` xóa bảng (`influxdb3 delete table --hard-delete now`) rồi ghi lại toàn bộ, nên khi đổi tham số sẽ không còn sót cờ cũ.

Schema legacy `server_metrics` được mô tả ở mục Project History.

## Weather Data Pipeline

Đã implement P3 + P4 trong `python/`:
1. **Source:** Open-Meteo (CC BY 4.0, không cần key, giới hạn 10.000 request/ngày).
   - Archive API (`best_match` = ECMWF IFS + ERA5 + ERA5-Land) cho dữ liệu lịch sử.
   - Forecast API cho các giờ gần nhất.
   - Dữ liệu là **mô hình/reanalysis trên lưới**, không phải quan trắc trạm: mượt, không có lỗi cảm biến. Đây là hạn chế cần nêu trong báo cáo.
2. **Collection** (`weather_collector.py`): một request cho mỗi location và mỗi chunk (mặc định 365 ngày); ghi đồng bộ theo batch 5.000 điểm.
3. **Cleaning** (`weather_cleaning.clean_payload`), theo thứ tự:
   1. kiểm tra cấu trúc payload và UTC;
   2. kiểm tra đơn vị;
   3. parse thời gian;
   4. bỏ giờ tương lai;
   5. ép kiểu;
   6. kiểm tra miền giá trị vật lý (`PHYSICAL_RANGES`: chỉ loại giá trị **không thể xảy ra**; giá trị cực đoan như bão Yagi được giữ lại);
   7. khử trùng;
   8. bỏ dòng rỗng.

   Mọi bước đều ghi số liệu vào `CleaningReport`.
4. **Verification:** sau mỗi lần ghi, collector đọc lại `count(*)` theo location trong cửa sổ vừa ghi, so với số điểm đã ghi, đồng thời báo số giờ bị thiếu, phân bố theo `data_source` và số null theo field. Nếu lệch thì exit code là 1.

Kết quả lần chạy ngày 2026-10-06:
- Dữ liệu 2024-01-01 → 2026-10-05: 72.636 dòng (24.212 dòng/location), không thiếu giờ nào, không có null, không có giá trị bị loại khi làm sạch.
- Bão Yagi hiện rõ ở Hà Nội ngày 6–8/9/2024: áp suất thấp nhất 982 hPa, gió giật 32,4 m/s, tổng mưa khoảng 170 mm.

## Anomaly Detection

Chức năng trọng tâm của đồ án. Các phương pháp được phép đánh giá: **Threshold, Z-score, IQR, Moving Average, Rolling Statistics.** **Không tự ý dùng Machine Learning hoặc Deep Learning.**

Quy trình bắt buộc: Inspect data → Analyze distribution → Compare methods → Select method → Implement → Evaluate. Phương pháp được chọn phải giải thích được trong báo cáo và khi bảo vệ. Chi tiết quy trình nằm trong skill `weather-timeseries-development`.

Các sự thật về dữ liệu rút ra từ P6 (`queries/weather_analysis/`) chi phối việc chọn phương pháp:
- **Chu kỳ ngày – đêm mạnh:** nhiệt độ TP.HCM trung bình 24,7 °C lúc 6h và 32,2 °C lúc 13h; biên độ ngày khoảng 10 °C trong mùa khô. Z-score trên toàn bộ chuỗi sẽ gắn cờ theo giờ trong ngày, nên phải dùng baseline theo giờ hoặc baseline cuộn.
- **Mùa vụ mạnh:**
  - Áp suất Hà Nội trung bình tháng 1 là 1019,6 hPa, tháng 7 là 1002,0 hPa (lệch khoảng 17 hPa). Ngưỡng áp suất cố định sẽ gắn cờ theo mùa.
  - Nhiệt độ Hà Nội dao động 7,2–40,2 °C, độ lệch chuẩn 5,4.
- **Lượng mưa có rất nhiều giá trị 0:** khoảng 70% số giờ không mưa; median của các giờ có mưa chỉ 0,2–0,3 mm. Phân phối không gần chuẩn nên **không dùng Z-score cho mưa**; dùng phân vị, IQR trên các giờ có mưa, hoặc tổng mưa cuộn.
- **Ca kiểm thử Yagi (Hà Nội), giờ VN:**
  - Áp suất thấp nhất **982,0 hPa lúc 2024-09-07 20:00**, gió giật cao nhất **32,4 m/s lúc 19:00**, mưa 114 mm trong ngày 07/09.
  - Biến thiên áp suất 3 giờ xuống tới **−5,2 hPa**.
  - Tương quan áp suất – gió giật là −0,895 trong bão, so với −0,216 ở tháng 08/2024.
  - Đây là ca **thay đổi đột ngột**, phù hợp với baseline cuộn.
- **Ca kiểm thử nắng nóng (TP.HCM, 04/2024):**
  - Nhiệt độ cao nhất ngày ở mức 35–39,2 °C **kéo dài cả tháng**; 158 giờ ≥ 35 °C, so với 58 giờ (04/2025) và 99 giờ (04/2026).
  - Đây là bất thường **kéo dài**: baseline cuộn 24h/7 ngày sẽ hấp thụ nó, nên cần baseline khí hậu (cùng tháng và cùng giờ của các năm khác).
  - Giờ nóng nhất toàn bộ dữ liệu là 39,4 °C lúc 2026-05-01 14:00, không thuộc đợt 2024.
- **Sự kiện chưa gán nhãn, dùng để kiểm tra false positive / true positive:** Hà Nội 2025-07-22 (988,6 hPa); Đà Nẵng có áp suất thấp nhất 988,5 hPa và gió giật 27 m/s.

## Grafana

- Mọi cấu hình được provisioning từ file. Grafana tự nạp lại file dashboard mỗi 5 giây; sửa dashboard bằng cách sửa JSON trong `grafana/dashboards_json/`.
- Datasource (`grafana/provisioning/datasources/influxdb3.yml`): tên `InfluxDB 3 Weather`, uid `influxdb3_weather`, URL `https://influxdb:8181` (mạng nội bộ Docker), `version: SQL`, `dbName: ${WEATHER_INFLUXDB_DATABASE}`. Compose truyền biến này vào Grafana với mặc định `weather`; đổi biến thì phải tạo lại container (`docker compose up -d grafana`), `restart` không nạp env mới. File có `deleteDatasources` để gỡ datasource legacy `InfluxDB 3 Core`.
- `ca-bundle.crt` được mount đè lên CA bundle hệ thống của Grafana để Grafana tin chứng chỉ self-signed của InfluxDB.
- **Dashboard `weather_analytics.json`** (uid `weather_analytics`, múi giờ `Asia/Ho_Chi_Minh`, mặc định 7 ngày, refresh 5 phút):
  - Biến:
    - `$location` (mặc định `hcm`);
    - `$time_bin` (interval: auto / 1h / 6h / 1d; auto chọn khoảng 200 điểm, tối thiểu 1h);
    - `$field` (multi, chỉ lọc bảng nhật ký).
  - Hàng **Tổng quan tức thời**: 5 stat có sparkline, 1 stat đếm cờ bất thường, 2 gauge (nhiệt độ 15/35/37/39 °C; gió giật Beaufort 10,8/17,2/24,5 m/s), bar gauge số giờ bị gắn cờ theo nhóm.
  - Hàng **Diễn biến chuỗi thời gian**: nhiệt độ + điểm sương (đường ngưỡng 35 °C); khí áp (trục trái) + mưa dạng cột (trục phải).
  - Hàng **Phát hiện bất thường**:
    - State Timeline 5 nhóm (nắng nóng kéo dài, áp suất thấp, gió giật, mưa 24h, dữ liệu kẹt), mức 0–3 tô màu bằng thresholds;
    - khí áp và gió giật, mỗi biểu đồ chồng chấm đỏ tại giờ bị gắn cờ.
  - Hàng **Nhật ký bất thường**: bảng `weather_anomalies`; cột Mức độ là badge màu theo regex (đỏ: cấp ≥ 10 / rất mạnh / rất to; cam: cấp 8–9 / mạnh / gay gắt; vàng: nắng nóng / mưa to / vừa; tím: kẹt).
  - Preset thời gian là **dashboard links** (Yagi Hà Nội 06–09/09/2024, nắng nóng TP.HCM 04/2024, 7 ngày gần nhất). Grafana 11.5.2 không hỗ trợ preset có nhãn trong timepicker: `quickRanges` của bản này chỉ là chuỗi tương đối của schema v2.
- **Quy ước truy vấn dashboard** (kiểm tra tự động bằng `check_dashboard.py` / `test_check_dashboard.py`):
  - Mọi truy vấn có `$__timeFrom()`, `$__timeTo()` và `location = '$location'`.
  - Gom nhóm bằng `date_bin(INTERVAL '$time_bin', time, TIMESTAMP '1970-01-01T17:00:00Z')`; origin 17:00Z để bin ngày/6h khớp giờ VN. DataFusion nhận `1h`/`6h`/`1d`.
  - SQL được gộp thành một dòng, nên **không dùng comment `--`** (comment sẽ nuốt phần còn lại của câu lệnh).
  - Gauge chỉ đọc 24 giờ cuối của khung. State Timeline sinh trục thời gian bằng `generate_series`, nên chỉ đọc bảng `weather_anomalies`.
  - Value mapping có màu **không tô màu** state-timeline với giá trị int64 (đã kiểm chứng bằng ảnh chụp). Dùng thresholds để tô màu, mapping chỉ để đổi chữ.
  - Đơn vị mưa dùng `suffix: mm`, không dùng `lengthmm`: `lengthmm` tự đổi 0,2 mm thành "200 µm".
- **Độ trễ đo qua `/api/ds/query` (2026-10-06, `check_dashboard.py`, mỗi truy vấn chạy một lần, đã warm):**

  | Kịch bản | Truy vấn đọc `weather_hourly` (min / trung vị / max) | Truy vấn nhẹ (`weather_anomalies`, gauge) |
  |---|---|---|
  | 7 ngày (3 location) | 57–138 ms, trung vị khoảng 90 ms | 60–123 ms |
  | Yagi 4 ngày | 57 / 134 / 260 ms | trung vị 81 ms |
  | Nắng nóng 30 ngày | 136 / 143 / 169 ms | trung vị 48 ms |
  | 1 năm | 1,31 / 1,48 / 1,57 s | trung vị 200 ms |

  - Mục tiêu dưới 100 ms chỉ đạt được với khung ngắn.
  - Riêng vòng HTTP Grafana → Flight SQL đã chiếm khoảng 40–80 ms.
  - Với khung dài, chi phí tỉ lệ với số file Parquet bị chạm tới (8.760 file/năm). `date_bin` giảm số điểm trả về nhưng không giảm số file phải đọc. Muốn nhanh hơn cần compaction (bản Enterprise) hoặc bảng downsample riêng; cả hai đều chưa làm.

## Environment Configuration

- `.env` ở root (git ignore), mẫu ở `.env.example`. Gồm: `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_DATABASE`, `WEATHER_INFLUXDB_DATABASE` (tùy chọn, mặc định `weather`), `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`.
- `INFLUXDB_TOKEN` vừa là token quản trị InfluxDB (`INFLUXDB3_AUTH_TOKEN` trong compose) vừa được truyền vào datasource Grafana.
- InfluxDB chạy **TLS**, nên `INFLUXDB_URL` phải là `https://localhost:8181`. Chứng chỉ là self-signed (SAN: `influxdb`, `influxdb3-core`, `localhost`, `127.0.0.1`), nên client Python dùng `verify_ssl=False`.
- `python/config.py` mặc định `INFLUXDB_DATABASE=server_monitoring` (tàn dư Phase 1; không script nào còn dùng giá trị này). Script weather dùng `WEATHER_INFLUXDB_DATABASE` (mặc định `weather`) hoặc `--database`, rồi thay vào config bằng `dataclasses.replace`.

## Development Commands

Chạy mọi lệnh từ thư mục root. Script Python import module cùng thư mục (`from config import ...`), nên phải **chạy theo đường dẫn file** (`python python/x.py`), không dùng `python -m`.

```bash
docker compose up -d                      # khởi động InfluxDB + Grafana
docker compose ps
docker compose logs -f influxdb           # tên service là "influxdb", tên container là "influxdb3-core"

.venv/Scripts/python.exe python/survey_weather_source.py --rows 12          # P2: khảo sát Open-Meteo (chỉ đọc, không ghi InfluxDB)

# Pipeline weather (P3/P4). Mọi lệnh tự đọc lại và kiểm tra count(*) sau khi ghi; lệch thì exit 1.
.venv/Scripts/python.exe python/weather_collector.py backfill --start 2024-01-01   # Archive API, mặc định tới hôm qua (UTC)
.venv/Scripts/python.exe python/weather_collector.py backfill --start 2024-09-05 --end 2024-09-09 --locations hanoi
.venv/Scripts/python.exe python/weather_collector.py recent --past-days 7          # Forecast API, không ghi đè archive
.venv/Scripts/python.exe python/weather_collector.py recent --interval-minutes 60  # lặp liên tục (gần thời gian thực)
.venv/Scripts/python.exe python/weather_collector.py verify                        # chỉ đọc: số dòng, giờ thiếu, null

# P6: chạy một file SQL (từng câu lệnh, in bảng kèm tiêu đề lấy từ comment "-- Query N:")
.venv/Scripts/python.exe python/run_sql.py queries/weather_analysis/03_yagi_hanoi.sql --max-rows 80

# P7: bảng so sánh phương pháp (Yagi, nắng nóng, 72h gần nhất, bất thường giả); khoảng 25 giây, chỉ đọc
.venv/Scripts/python.exe python/evaluate_anomaly.py [--k 3.0] [--sensitivity]
.venv/Scripts/python.exe python/anomaly_job.py --dry-run   # xem trước số dòng, không động vào DB
.venv/Scripts/python.exe python/anomaly_job.py             # xóa rồi ghi lại weather_anomalies, đối chiếu count(*)

# P8: kiểm tra dashboard. Phần tĩnh không cần mạng; phần live chạy 18 truy vấn x 6 kịch bản qua Grafana, khoảng 30 giây
.venv/Scripts/python.exe python/check_dashboard.py [--static-only] [--scenarios yagi,heatwave]
docker compose up -d grafana              # sau khi đổi env/provisioning datasource (restart không nạp env mới)

# Container đã có sẵn INFLUXDB3_AUTH_TOKEN nên CLI bên trong không cần --token
docker exec influxdb3-core influxdb3 query --host https://127.0.0.1:8181 --tls-no-verify \
  -d weather "SELECT location, count(*) FROM weather_hourly GROUP BY location"
```

Chạy lại `backfill` cho khoảng 2 tuần gần nhất sau vài ngày: ERA5 trễ khoảng 6 ngày, nên giá trị archive của những ngày gần nhất (tạm lấy từ IFS) sẽ được cập nhật. Việc ghi đè là idempotent nên chạy lại an toàn.

Grafana: http://localhost:3000/d/weather_analytics (đăng nhập bằng tài khoản trong `.env`). Trước khi demo: chạy `weather_collector.py recent`, rồi `anomaly_job.py`.

## Testing

- Không dùng pytest (chưa cài). Test là các hàm `test_*` dùng `assert` thuần, có `main()` riêng, chạy theo đường dẫn file:
  - `.venv/Scripts/python.exe python/test_weather_cleaning.py`: 11 test cho cleaning, schema/line protocol (gồm cả `weather_anomalies`) và chia chunk ngày; không cần mạng, không cần DB.
  - `.venv/Scripts/python.exe python/test_run_sql.py`: test việc tách câu lệnh SQL (dấu `;` trong comment không được tách).
  - `.venv/Scripts/python.exe python/test_weather_anomaly.py`: 14 test cho các detector (gồm `persistent_climate_zscore` và các hàm severity), dùng dữ liệu tổng hợp có đáp án. Ví dụ: Z-score khí hậu không gắn cờ chu kỳ ngày – đêm và loại năm đang xét khỏi baseline; rolling chỉ dùng các giờ trước điểm đang xét; IQR thất bại khi ≥ 75% giá trị bằng 0.
  - `.venv/Scripts/python.exe python/test_check_dashboard.py`: 3 test. Gồm thay biến dashboard (không đụng `$__macro`), phát hiện truy vấn thiếu filter thời gian/location, và dashboard JSON đã commit thỏa mọi quy tắc.
  - `archive/phase1-essay/benchmark/test_storage_logic.py`: test của Phase 1 (đã archive).
- Kiểm thử tích hợp của pipeline nằm sẵn trong collector: sau mỗi lần ghi, lệnh tự đọc lại và so `count(*)`.
- Với code mới:
  - Tách logic thuần (parse, cleaning, anomaly detection) khỏi I/O để test được mà không cần InfluxDB.
  - Kiểm thử tích hợp bằng cách ghi rồi đọc lại (`count(*)`, min/max time, kiểm tra NULL) trên database đang chạy.
- Không báo "hoàn thành" khi chưa chạy code thực tế và xem kết quả.

## Coding Rules

- Theo phong cách code hiện có:
  - type hints và docstring;
  - cấu hình bằng `@dataclass(frozen=True)` với `load()` đọc từ env;
  - CLI bằng `argparse`;
  - log bằng `print` với tiền tố `[INFO]`/`[ERROR]`, lỗi ghi ra stderr và `sys.exit(1)`.
- Trên Windows, script in ký tự tiếng Việt nên `reconfigure` stdout sang UTF-8 (như các script benchmark đã làm).
- Dùng lại `python/config.py` thay vì viết logic kết nối mới.
- Giữ code đơn giản; không thêm lớp trừu tượng hay framework khi chưa cần.

## Security Rules

- Không commit `.env`, mật khẩu, API key, token InfluxDB, mật khẩu Grafana, private key, TLS key (`certs/` đã git ignore).
- `.env.example` chỉ chứa placeholder. Khi thêm biến môi trường mới (ví dụ API key của nguồn thời tiết), thêm placeholder vào `.env.example`.
- Không in token hay secret ra log/output; dùng `sanitized_summary()` khi cần in cấu hình.
- Nếu phát hiện secret thật trong repo: không in ra, báo vị trí, đề xuất rotate, sửa cấu hình theo hướng an toàn.

## Do Not Do

- Không thêm Kafka, Redis, RabbitMQ, Kubernetes, Spark, Flink, Airflow, microservices, hạ tầng cloud, MLflow (trừ khi được yêu cầu rõ ràng).
- Không dùng ML/Deep Learning cho anomaly detection khi chưa được yêu cầu.
- Không mặc định schema weather trước khi khảo sát dữ liệu thật.
- Không viết lại project từ đầu; tái sử dụng phần còn hoạt động.
- Không xóa code hoặc cấu hình chưa hiểu. Quy trình: Inspect → Classify → Explain → Approve/Apply.
- Không dùng `git reset --hard`, `git clean -fd`, force-push; không discard thay đổi chưa commit của người dùng.
- Không xóa Docker volume (`influxdb3_data`, `grafana_data`) hay database legacy khi chưa được yêu cầu.
- Không sửa code trong `archive/`.

## Current Development Phase

Roadmap đồ án:
- P1 Repository Cleanup
- P2 Weather Data Source
- P3 Data Collection
- P4 Data Cleaning
- P5 InfluxDB Weather Schema
- P6 Queries & Analysis
- P7 Anomaly Detection
- P8 Grafana Dashboard
- P9 Testing & Evaluation
- P10 Demo + Report

**P1 hoàn thành ngày 2026-10-06:** benchmark và kịch bản demo đã archive, artifact đã xóa, cấu hình HTTPS đã sửa, tag `phase1-essay` đã tạo.

**P2 hoàn thành ngày 2026-10-06:** chọn Open-Meteo; schema được chốt cùng người dùng (xem Data Model).

**P3 + P4 hoàn thành ngày 2026-10-06:** collector và cleaning đã chạy trên dữ liệu thật, 10/10 unit test pass, `count(*)` khớp. P5 (schema) thực chất đã được chốt từ P2 và được tạo khi ghi lần đầu.

**Đã xử lý `query-file-limit`** bằng cách tăng lên 50000 (xem mục InfluxDB Conventions).

**P6 hoàn thành ngày 2026-10-06:** SQL phân tích nằm ở `queries/weather_analysis/`, chạy bằng `python/run_sql.py`. Kết quả P6 là đầu vào cho các bước "Inspect data" và "Analyze distribution" của P7.

**P7 hoàn thành ngày 2026-10-06** (commit `a2e360c`):
- **Quyết định đã chốt:**
  1. Baseline khí hậu (cùng tháng và cùng giờ địa phương) chỉ dùng dữ liệu 2024–2026, so mỗi năm với các năm còn lại (leave-one-year-out). Không nạp thêm lịch sử, vì mỗi giờ nạp bù là một file Parquet. Baseline mỏng (khoảng 2 năm) là hạn chế cần ghi trong báo cáo.
  2. Kết quả lưu ở bảng `weather_anomalies` (xem Data Model), mỗi lần chạy thì xóa rồi ghi lại toàn bộ.
  3. **Phương pháp được chọn** (cấu hình nằm ở `anomaly_job.selected_methods()`):
     - áp suất: `climate_zscore` k = 3, low;
     - gió giật: `iqr` k = 3 theo tháng, cộng `threshold` 17,2 m/s;
     - mưa 24h: `iqr` k = 3 trên các khoảng có mưa (≥ 1 mm) theo tháng, cộng `threshold` 50 mm;
     - nhiệt độ: `persistent_climate_zscore` (trung bình z khí hậu 168h ≥ 1,0, high);
     - chất lượng dữ liệu: `stuck` ≥ 6 giờ cho nhiệt độ và áp suất.
- **Kết quả so sánh** (`evaluate_anomaly.py`, k = 3; số liệu cho báo cáo):
  - **Yagi (áp suất, low):** Z-score khí hậu tốt nhất: phát hiện **sớm 24 giờ** so với lúc áp suất thấp nhất, 41/72 giờ bị gắn cờ, 0,7 đợt báo động giả mỗi năm. Rolling 24h có 46 đợt/năm. Tendency 3h ≤ −3 hPa vô dụng (219 đợt/năm, vì dao động áp suất ngày – đêm ở vùng nhiệt đới đủ lớn để vượt ngưỡng này).
  - **Nắng nóng TP.HCM 04/2024:**
    - Mọi phương pháp xét từng giờ đều thất bại ở k = 3, vì từng giờ chỉ lệch khoảng +2σ. Ở k = 2, Z-score khí hậu bắt được 11/30 ngày nhưng có 67 đợt báo động giả mỗi năm.
    - Threshold ≥ 35 °C bắt được 30/30 ngày, nhưng nó đo mức độ nguy hiểm tuyệt đối chứ không đo bất thường (58 đợt/năm).
    - `persistent_climate_zscore` bắt được **18/30 ngày** với 6,9 đợt báo động giả mỗi năm. Bất thường nằm ở độ kéo dài.
  - **Bất thường giả (TP.HCM 2025):**
    - Z-score khí hậu có recall spike 0,85–0,9 nhưng precision chỉ 0,14–0,17, vì gắn cờ khoảng 250 giờ "thật" mỗi năm với nhiệt độ.
    - Rolling 24h hoạt động tốt với áp suất (recall 0,85) nhưng kém với nhiệt độ (0,25), vì chu kỳ ngày – đêm làm độ lệch chuẩn 24h phình to.
    - Detector stuck có recall 1,0; precision 0,88 là do chính cách gán nhãn.
  - **72 giờ gần nhất ở TP.HCM (tới 2026-10-06 15:00 giờ VN):** mưa 24h tối đa 19,2 mm, gió giật tối đa 8,5 m/s. Không phương pháp nào được chọn gắn cờ, nghĩa là đây là mưa bình thường của mùa mưa.
- **Lần chạy `anomaly_job.py` (dữ liệu tới 2026-10-06 08:00 UTC):** 10.813 dòng (HCM 3.418, Hà Nội 2.905, Đà Nẵng 4.490). Cả 18 nhóm `count(*)` khớp với số dòng đã ghi. Chạy lại lần 2 thì bảng bị xóa và ghi lại, vẫn 10.813 dòng và chỉ còn một giá trị `detected_at`.
  - `persistent_climate_zscore` chiếm khoảng 72% số dòng, vì nó gắn cờ khoảng 10% số giờ: mỗi đợt kéo dài khoảng 1 tuần.
  - **Stuck gắn cờ 12 giờ ở Hà Nội** (đêm 27–28/02/2024 và 20/02/2025, nhiệt độ đứng yên 6 giờ). Áp suất vẫn biến thiên trong cùng lúc, nên đây là **đêm đông lặng gió tự nhiên**, không phải lỗi feed. Cải tiến có thể làm: chỉ gắn cờ khi nhiều field cùng đứng yên.

**P8 hoàn thành ngày 2026-10-06** (chờ commit). Chi tiết dashboard và quy ước truy vấn nằm ở mục Grafana.
- **Đã dọn legacy (người dùng duyệt):**
  - đã xóa `server_monitoring.json`, `python/generator.py`, `queries/01–03*.sql`, `queries/README.md`;
  - datasource `InfluxDB 3 Core` (uid `influxdb3_datasource`) được gỡ bằng `deleteDatasources`;
  - datasource FlightSQL tạo tay (uid `PDE06B032DBEFDB92`) đã xóa qua API.

  Grafana hiện chỉ còn 1 datasource (`influxdb3_weather`, default, Health OK) và 1 dashboard (`weather_analytics`).
- **Khác với yêu cầu ban đầu:**
  - preset thời gian làm bằng dashboard links (lý do ở mục Grafana);
  - `dbName` lấy từ `WEATHER_INFLUXDB_DATABASE` chứ không dùng `INFLUXDB_DATABASE`, vì `.env` vẫn đặt `INFLUXDB_DATABASE=server_monitoring`;
  - không có hàng "So sánh 3 vùng" như kế hoạch cũ; người dùng thay bằng bố cục 4 hàng.
- **Kiểm thử:**
  - `check_dashboard.py`: 108/108 truy vấn OK (18 truy vấn × 6 kịch bản: 7 ngày × 3 location, Yagi, nắng nóng, 1 năm).
  - Log Grafana sau `docker compose restart grafana` không có error.
  - 30/30 unit test pass.
  - Đã chụp ảnh dashboard bằng Chrome headless qua DevTools Protocol (script tạm, không nằm trong repo) và xem trực tiếp. Hai lỗi chỉ ảnh chụp mới lộ ra đã được sửa: state-timeline không lên màu, mưa hiển thị µm.
- **Hiển thị khớp kết quả P7:**
  - Yagi: chấm đỏ tại 982 hPa và 32,4 m/s.
  - State Timeline cho thấy áp suất thấp được gắn cờ trước gió và mưa.
  - Nắng nóng TP.HCM 04/2024 hiện thành các dải cam/đỏ kéo dài.
  - 7 ngày gần nhất ở TP.HCM: 0 cờ, mưa 24h 19,2 mm.

**Tiếp theo: P9** (Testing & Evaluation).

Cập nhật mục này mỗi khi chuyển phase.

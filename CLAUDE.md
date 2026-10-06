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

Hiện tại mới có hạ tầng và demo server monitoring legacy chạy trên kiến trúc này. Các tầng weather chưa được implement.

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
  survey_weather_source.py  # P2: script khảo sát nguồn (chỉ đọc)
  generator.py            # LEGACY — sinh dữ liệu server cho dashboard legacy; xóa cùng dashboard ở P8
queries/weather_analysis/ # P6: 5 file SQL phân tích weather (giờ VN = time + 7h), có README
queries/*.sql             # LEGACY — 15 câu SQL cho server_metrics (dashboard legacy)
grafana/
  provisioning/           # KEEP — datasource + dashboard provider
  dashboards_json/        # LEGACY — dashboard server_monitoring.json
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
- Datasource (`grafana/provisioning/datasources/influxdb3.yml`): uid `influxdb3_datasource`, URL `https://influxdb:8181` (mạng nội bộ Docker), `version: SQL`. Hiện **`dbName` đang hard-code `server_monitoring`**. Khi có database weather, phải thêm datasource thứ hai với uid mới hoặc đổi `dbName`. Docker-compose đã truyền sẵn biến `INFLUXDB_DATABASE` vào container Grafana nhưng file datasource chưa dùng biến này.
- `ca-bundle.crt` được mount đè lên CA bundle hệ thống của Grafana để Grafana tin chứng chỉ self-signed của InfluxDB.
- Dashboard legacy: `server_monitoring.json` (uid `server_monitoring_influxdb3`). Các biến `$host` và `$region` đã khai báo nhưng chưa panel nào dùng.

## Environment Configuration

- `.env` ở root (git ignore), mẫu ở `.env.example`. Gồm: `INFLUXDB_URL`, `INFLUXDB_TOKEN`, `INFLUXDB_DATABASE`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`.
- `INFLUXDB_TOKEN` vừa là token quản trị InfluxDB (`INFLUXDB3_AUTH_TOKEN` trong compose) vừa được truyền vào datasource Grafana.
- InfluxDB chạy **TLS**, nên `INFLUXDB_URL` phải là `https://localhost:8181`. Chứng chỉ là self-signed (SAN: `influxdb`, `influxdb3-core`, `localhost`, `127.0.0.1`), nên client Python dùng `verify_ssl=False`.
- `python/config.py` mặc định `INFLUXDB_DATABASE=server_monitoring` (cho demo legacy). Script weather dùng `WEATHER_INFLUXDB_DATABASE` (mặc định `weather`) hoặc `--database`, rồi thay vào config bằng `dataclasses.replace`.

## Development Commands

Chạy mọi lệnh từ thư mục root. Script Python import module cùng thư mục (`from config import ...`), nên phải **chạy theo đường dẫn file** (`python python/x.py`), không dùng `python -m`.

```bash
docker compose up -d                      # khởi động InfluxDB + Grafana
docker compose ps
docker compose logs -f influxdb           # tên service là "influxdb", tên container là "influxdb3-core"

.venv/Scripts/python.exe python/generator.py --interval 1 --iterations 10   # demo legacy; --iterations 0 = chạy liên tục
.venv/Scripts/python.exe python/survey_weather_source.py --rows 12          # P2: khảo sát Open-Meteo (chỉ đọc, không ghi InfluxDB)

# Pipeline weather (P3/P4). Mọi lệnh tự đọc lại và kiểm tra count(*) sau khi ghi; lệch thì exit 1.
.venv/Scripts/python.exe python/weather_collector.py backfill --start 2024-01-01   # Archive API, mặc định tới hôm qua (UTC)
.venv/Scripts/python.exe python/weather_collector.py backfill --start 2024-09-05 --end 2024-09-09 --locations hanoi
.venv/Scripts/python.exe python/weather_collector.py recent --past-days 7          # Forecast API, không ghi đè archive
.venv/Scripts/python.exe python/weather_collector.py recent --interval-minutes 60  # lặp liên tục (gần thời gian thực)
.venv/Scripts/python.exe python/weather_collector.py verify                        # chỉ đọc: số dòng, giờ thiếu, null

# P6: chạy một file SQL (từng câu lệnh, in bảng kèm tiêu đề lấy từ comment "-- Query N:")
.venv/Scripts/python.exe python/run_sql.py queries/weather_analysis/03_yagi_hanoi.sql --max-rows 80

# Container đã có sẵn INFLUXDB3_AUTH_TOKEN nên CLI bên trong không cần --token
docker exec influxdb3-core influxdb3 query --host https://127.0.0.1:8181 --tls-no-verify \
  -d weather "SELECT location, count(*) FROM weather_hourly GROUP BY location"
```

Chạy lại `backfill` cho khoảng 2 tuần gần nhất sau vài ngày: ERA5 trễ khoảng 6 ngày, nên giá trị archive của những ngày gần nhất (tạm lấy từ IFS) sẽ được cập nhật. Việc ghi đè là idempotent nên chạy lại an toàn.

Grafana: http://localhost:3000 (đăng nhập bằng tài khoản trong `.env`).

## Testing

- Không dùng pytest (chưa cài). Test là các hàm `test_*` dùng `assert` thuần, có `main()` riêng, chạy theo đường dẫn file:
  - `.venv/Scripts/python.exe python/test_weather_cleaning.py`: 10 test cho cleaning, schema/line protocol và chia chunk ngày; không cần mạng, không cần DB.
  - `.venv/Scripts/python.exe python/test_run_sql.py`: test việc tách câu lệnh SQL (dấu `;` trong comment không được tách).
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

**Đang làm: P6 (Queries & Analysis) và P7 (Anomaly Detection), bắt đầu 2026-10-06.**
- **P6:** SQL phân tích nằm ở `queries/weather_analysis/`, chạy bằng `python/run_sql.py`. Kết quả P6 là đầu vào cho các bước "Inspect data" và "Analyze distribution" của P7.
- **P7:** đã có kế hoạch, **chưa implement**.
  - Sẽ có module `python/weather_anomaly.py` (hàm thuần, có test), so sánh Threshold, Z-score, IQR và Rolling Statistics với baseline 24h và 7 ngày.
  - Ca kiểm thử thật: bão Yagi (Hà Nội, 09/2024) và nắng nóng (TP.HCM, 04–05/2024).
  - Người dùng chọn phương pháp sau khi xem bảng so sánh.
  - **Quyết định đã chốt ngày 2026-10-06:**
    1. Baseline khí hậu (cùng tháng và cùng giờ địa phương) chỉ dùng dữ liệu 2024–2026, so mỗi năm với các năm còn lại (leave-one-year-out). Không nạp thêm lịch sử, vì mỗi giờ nạp bù là một file Parquet. Baseline mỏng (khoảng 2 năm) là hạn chế cần ghi trong báo cáo.
    2. Kết quả bất thường lưu vào **bảng InfluxDB riêng**, tách khỏi `weather_hourly`, để Grafana dùng ở P8. Thiết kế bảng (tag, field) phải trình bày cho người dùng trước khi ghi.

Cập nhật mục này mỗi khi chuyển phase.

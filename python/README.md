# Python Module — Weather Pipeline

Thu thập dữ liệu thời tiết theo giờ từ Open-Meteo, làm sạch, ghi vào **InfluxDB 3 Core**, phát hiện bất thường và kiểm tra dashboard Grafana. Schema và các quy ước đầy đủ nằm trong `CLAUDE.md` ở root.

## Các module

| File | Vai trò |
|---|---|
| `config.py` | Đọc kết nối InfluxDB từ `.env` (`InfluxDBConfig.load()`) |
| `open_meteo.py` | Client Open-Meteo: danh sách địa điểm, ánh xạ tên trường API → field, đơn vị mong đợi, retry |
| `weather_schema.py` | Schema `weather_hourly` và `weather_anomalies`, miền giá trị vật lý hợp lệ, `to_point()` / `anomaly_to_point()` |
| `weather_cleaning.py` | Các bước làm sạch dạng hàm thuần, kèm `CleaningReport` đếm số liệu từng bước |
| `weather_collector.py` | CLI `backfill` / `recent` / `verify` |
| `run_sql.py` | Chạy một file `.sql` từng câu lệnh và in bảng (dùng cho `queries/weather_analysis/`) |
| `weather_anomaly.py` | Các detector dạng hàm thuần (threshold, Z-score, Z-score khí hậu, IQR, rolling, stuck) và hàm đánh giá |
| `evaluate_anomaly.py` | So sánh các phương pháp trên dữ liệu thật (chỉ đọc) |
| `anomaly_job.py` | Chạy các phương pháp đã chọn, xóa rồi ghi lại bảng `weather_anomalies` |
| `check_dashboard.py` | Kiểm tra dashboard Grafana: quy tắc tĩnh + chạy mọi truy vấn panel qua Grafana |
| `survey_weather_source.py` | Script khảo sát nguồn dữ liệu của P2 (chỉ đọc) |
| `test_*.py` | Unit test (không cần mạng hay database) |

## Sử dụng

Chạy từ thư mục root của repo, trong `.venv` (`pip install influxdb3-python python-dotenv numpy`):

```bash
python python/weather_collector.py backfill --start 2024-01-01          # Archive API → hôm qua (UTC)
python python/weather_collector.py backfill --start 2024-09-05 --end 2024-09-09 --locations hanoi
python python/weather_collector.py recent --past-days 7                 # Forecast API, không ghi đè archive
python python/weather_collector.py recent --interval-minutes 60         # chạy liên tục, Ctrl+C để dừng
python python/weather_collector.py verify                               # chỉ đọc: số dòng, giờ thiếu, null

python python/run_sql.py queries/weather_analysis/03_yagi_hanoi.sql     # SQL phân tích
python python/evaluate_anomaly.py                                       # so sánh phương pháp (chỉ đọc)
python python/anomaly_job.py --dry-run                                  # xem trước số cờ
python python/anomaly_job.py                                            # xóa + ghi lại weather_anomalies
python python/check_dashboard.py                                        # kiểm tra dashboard Grafana

python python/test_weather_cleaning.py
python python/test_run_sql.py
python python/test_weather_anomaly.py
python python/test_check_dashboard.py
```

Tùy chọn chung:
- `--database`: mặc định lấy từ `$WEATHER_INFLUXDB_DATABASE`, nếu không có thì là `weather`.
- `--locations`: `all` hoặc danh sách như `hcm,hanoi`.

Lệnh `backfill` có thêm `--chunk-days` (mặc định 365) và `--batch-size` (mặc định 5000).

Sau mỗi lần ghi, collector và `anomaly_job.py` đọc lại `count(*)` và so với số điểm đã ghi. Nếu lệch, lệnh kết thúc với exit code 1.

`check_dashboard.py` đọc `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` từ `.env` và không in ra. Grafana mặc định ở `http://localhost:3000`; đổi bằng `--grafana-url`.

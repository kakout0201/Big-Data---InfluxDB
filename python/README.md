# Python Module — Weather Pipeline

Thu thập dữ liệu thời tiết theo giờ từ Open-Meteo, làm sạch và ghi vào **InfluxDB 3 Core**. Schema và các quy ước đầy đủ nằm trong `CLAUDE.md` ở root.

## Các module

| File | Vai trò |
|---|---|
| `config.py` | Đọc kết nối InfluxDB từ `.env` (`InfluxDBConfig.load()`) |
| `open_meteo.py` | Client Open-Meteo: danh sách địa điểm, ánh xạ tên trường API → field, đơn vị mong đợi, retry |
| `weather_schema.py` | Schema `weather_hourly`, miền giá trị vật lý hợp lệ, hàm `to_point()` |
| `weather_cleaning.py` | Các bước làm sạch dạng hàm thuần, kèm `CleaningReport` đếm số liệu từng bước |
| `weather_collector.py` | CLI `backfill` / `recent` / `verify` |
| `test_weather_cleaning.py` | Unit test (không cần mạng hay database) |
| `survey_weather_source.py` | Script khảo sát nguồn dữ liệu của P2 (chỉ đọc) |
| `generator.py` | **Legacy** (Phase 1): sinh dữ liệu giám sát server cho dashboard cũ |

## Sử dụng

Chạy từ thư mục root của repo, trong `.venv` (`pip install influxdb3-python python-dotenv`):

```bash
python python/weather_collector.py backfill --start 2024-01-01          # Archive API → hôm qua (UTC)
python python/weather_collector.py backfill --start 2024-09-05 --end 2024-09-09 --locations hanoi
python python/weather_collector.py recent --past-days 7                 # Forecast API, không ghi đè archive
python python/weather_collector.py recent --interval-minutes 60         # chạy liên tục, Ctrl+C để dừng
python python/weather_collector.py verify                               # chỉ đọc: số dòng, giờ thiếu, null
python python/test_weather_cleaning.py
```

Tùy chọn chung:
- `--database`: mặc định lấy từ `$WEATHER_INFLUXDB_DATABASE`, nếu không có thì là `weather`.
- `--locations`: `all` hoặc danh sách như `hcm,hanoi`.

Lệnh `backfill` có thêm `--chunk-days` (mặc định 365) và `--batch-size` (mặc định 5000).

Sau mỗi lần ghi, collector đọc lại `count(*)` theo từng địa điểm trong khoảng thời gian vừa ghi và so với số điểm đã ghi. Nếu lệch, lệnh kết thúc với exit code 1.

## Demo legacy (Phase 1)

```bash
python python/generator.py --interval 1 --iterations 10    # ghi vào server_monitoring.server_metrics
```

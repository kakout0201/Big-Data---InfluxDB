# Nghiên cứu InfluxDB 3 và xây dựng hệ thống giám sát dữ liệu chuỗi thời gian thời gian thực

## 1. Giới thiệu Project

Đồ án môn học **Big Data** tập trung nghiên cứu kiến trúc công nghệ lõi của **InfluxDB 3** (dựa trên hệ sinh thái Apache Arrow, DataFusion và lưu trữ Parquet) và xây dựng hoàn chỉnh hệ thống giám sát hạ tầng thời gian thực (Real-time Time-Series Infrastructure Monitoring Pipeline).

---

## 2. Mục tiêu Pipeline Thực nghiệm

Hệ thống được thiết kế theo luồng kiến trúc:

```text
Python Data Generator
        │
        │ Batch / Line Protocol
        ▼
InfluxDB 3 (Write Path → WAL → Parquet Storage)
        │
        │ Apache Arrow / DataFusion Engine
        ▼
SQL Query Engine
        │
        │ Flight SQL / HTTP API
        ▼
Grafana Dashboard
```

---

## 3. Công nghệ Dự kiến Sử dụng

* **Database Core:** InfluxDB 3 (Engine: Apache Arrow, Apache DataFusion, Apache Parquet)
* **Data Ingestion:** Python (InfluxDB Client / Flight SQL)
* **Containerization & Orchestration:** Docker & Docker Compose
* **Visualization:** Grafana Dashboard
* **Query Language:** SQL (DataFusion SQL dialect)

---

## 4. Dataset Mô phỏng

Hệ thống mô phỏng dữ liệu telemetry hạ tầng phân tán:
* **Hạ tầng:** 10 máy chủ (server nodes)
* **Khu vực địa lý:** 3 region (`us-east-1`, `ap-southeast-1`, `eu-central-1`)
* **Chỉ số theo dõi (Metrics):**
  * CPU usage (%)
  * Memory usage (%)
  * Network traffic (MB/s In/Out)
  * Error rate (req/s)
  * Timestamp (nanosecond precision)

---

## 5. Lộ trình Thực hiện (Project Phases)

* **Phase 1:** Environment Setup (Completed)
* **Phase 2:** InfluxDB 3 Deployment (Completed)
* **Phase 3:** Data Model Design (Completed)
* **Phase 4:** Python Data Generator (Completed)
* **Phase 5:** SQL Analytics & Aggregations (Completed)
* **Phase 6:** Batch Ingestion & Optimization
* **Phase 7:** Performance Benchmarking (Write/Read throughput, Compression ratio)
* **Phase 8:** Grafana Dashboard Setup
* **Phase 9:** End-to-End Integration Testing
* **Phase 10:** Presentation & Final Report

---

## 6. Cấu trúc Dự án

```text
INFLUXDB/
│
├── .git/               # Quản lý phiên bản Git
├── .gitignore          # File cấu hình bỏ qua file rác / nhị phân / môi trường ảo
├── .env.example        # Mẫu biến môi trường (không chứa secret thật)
├── docker-compose.yml  # Cấu hình container InfluxDB 3 Core
├── README.md           # Tài liệu tổng quan dự án
│
├── python/             # Module Data Generator & InfluxDB Ingestion scripts
│   ├── config.py
│   ├── generator.py
│   └── README.md
│
├── queries/            # Module tập hợp các câu truy vấn SQL Analytics
│   ├── 01_basic.sql
│   ├── 02_aggregation.sql
│   ├── 03_time_series.sql
│   └── README.md
│
├── benchmark/          # Module kịch bản kiểm thử hiệu năng và báo cáo
│   └── README.md
│
├── grafana/            # Module cấu hình datasource và dashboard provisioning
│   └── README.md
│
├── docs/               # Module tài liệu nghiên cứu và báo cáo đồ án
│   └── README.md
│
└── .venv/              # Môi trường ảo Python (Local only - ignored by Git)
```

---

## 7. InfluxDB 3 Core Local Setup

### Yêu cầu tiên quyết
* Docker Engine 24+ & Docker Compose v2+
* Cổng mạng `8181` khả dụng.

### Cấu hình InfluxDB 3 Core
* **Docker Image:** `influxdb:3-core`
* **Container Name:** `influxdb3-core`
* **Exposed Port:** `8181`
* **Storage Volume:** Docker named volume `influxdb3_data` (lưu trữ metadata, WAL và dữ liệu Parquet).
* **Default Database:** `server_monitoring`
* **Retention Policy:** `30d` (30 ngày)

### Vận hành Container
* **Khởi động:**
  ```bash
  docker compose up -d
  ```
* **Dừng container:**
  ```bash
  docker compose stop
  ```
* **Khởi động lại:**
  ```bash
  docker compose start
  ```
* **Kiểm tra trạng thái:**
  ```bash
  docker compose ps
  docker compose logs -f influxdb
  ```
* **Kiểm tra API Health:**
  ```bash
  curl -H "Authorization: Bearer <INFLUXDB_TOKEN>" http://localhost:8181/health
  ```
*(Lưu ý: Token quản trị được lưu trong file `.env` local và tuyệt đối không commit lên Git).*


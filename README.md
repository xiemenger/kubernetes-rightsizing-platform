# Kubernetes Rightsizing Recommendation Platform

## 1. Project Overview

**Kubernetes Rightsizing Recommendation Platform** analyzes workload resource requests against observed utilization and cost data, then produces rightsizing recommendations with estimated weekly savings.

**Purpose**

- Generate CPU and memory rightsizing recommendations for Kubernetes workloads
- Estimate cost savings (or cost increases) for aggressive and conservative policies
- Persist results for reporting, notification, and API consumption

**Data sources**

| Source | Role |
|--------|------|
| **Kubernetes** | Current CPU and memory resource requests per service |
| **Prometheus** | P95 CPU and memory utilization over a rolling observation window |
| **Cloudability** | Actual weekly service cost (`weekly_cost_usd`) |
| **AWS normalized node pricing** | Fallback for savings estimation when Cloudability cost is missing |

**Demo vs production**

| Area | Implemented in this repo (demo) | Production design / future |
|------|----------------------------------|----------------------------|
| Collectors | Mock implementations with realistic static data | Real K8s, Prometheus, Cloudability, and AWS pricing APIs |
| Job execution | Celery worker + Redis | Kubernetes Job/Pod or in-cluster worker |
| Job trigger | `POST /api/v1/jobs` | Weekly Kubernetes CronJob (Tuesday) per cluster |
| Report delivery | `generate_report_summary()` + `MockEmailSender` (modules; not wired into Celery yet) | SES, SMTP, SendGrid, or internal notification services |
| Detailed UI | `GET /api/v1/recommendations` | Frontend report page linked from email |
| CI/CD deploy | Echo scripts simulating deploy/verify/trigger | Real `kubectl` + cluster kubeconfig per job |

---

## 2. Architecture

The application follows **Clean Architecture**: the **RightsizerEngine** is pure domain logic; collectors, persistence, API, reports, and notifications are adapters around it.

### Major layers

| Layer | Responsibility |
|-------|----------------|
| **REST API** | Health, job lifecycle, recommendations query |
| **Celery async pipeline** | `run_rightsizing_job` — collectors → engine → PostgreSQL |
| **Collectors** | Kubernetes specs, Prometheus P95, Cloudability costs, AWS pricing |
| **RightsizerEngine** | Aggressive/conservative CPU and memory targets; savings estimation |
| **PostgreSQL persistence** | `jobs` and `recommendations` tables (SQLAlchemy ORM) |
| **Report generator** | `ReportSummary` / `ReportRow` from persisted recommendations |
| **Notification service** | Plain-text weekly email via `MockEmailSender` |
| **GitLab CI/CD** | Test, build, smoke test, per-cluster deploy/verify/trigger |
| **Multi-cluster deployment** | Inventory in `deploy/clusters.yaml`; one GitLab job per cluster |

### Architecture diagram

```


Kubernetes          Prometheus          Cloudability          AWS Pricing
     │                   │                    │                    │
     └───────────────────┴────────────────────┴────────────────────┘
                                    │
                                    ▼
                              Collectors
                                    │
                                    ▼
                           RightsizerEngine
                                    │
                                    ▼
                              PostgreSQL
                              /          \
                             /            \
                            ▼              ▼
               Recommendations API   Report Generator
                                             ↓
                                   Notification Service
                                             ↓
                                        Email Recipient

```

---

## 3. End-to-End Workflow

### Manual path (demo)

```
POST /api/v1/jobs
        ↓
   Celery task (run_rightsizing_job)
        ↓
   Collectors (mock)
        ↓
   RightsizerEngine
        ↓
   PostgreSQL
        ↓
   Report Generator          ← implemented; call after job completes
        ↓
   Email Notification        ← MockEmailSender (demo)
        ↓
GET /api/v1/recommendations
```

1. Client creates a job → row `pending`, Celery task enqueued.
2. Worker sets `running`, runs collectors and engine, persists recommendations, sets `completed` (or `failed` on error).
3. Operator or automation builds `ReportSummary` from recommendations and sends email (demo: `MockEmailSender`).
4. Recipients use the report link and/or query the Recommendations API for full detail.

### Scheduled path (production design)

```
Kubernetes CronJob (Tuesday 08:00 UTC)
        ↓
   Weekly execution per cluster
        ↓
   Same pipeline: Collectors → RightsizerEngine → PostgreSQL
        ↓
   Report Generator → Email → Recommendations API
```

Manifest: `deploy/k8s/cronjob.yaml` (`schedule: "0 8 * * 2"`). Demo CI simulates weekly triggers via `scripts/trigger_weekly_job.sh` after per-cluster verify jobs.

---

## 4. Recommendation Logic

Recommendations are driven by **Prometheus P95 metrics** (not averages), compared to current Kubernetes requests.

| Policy | Headroom (default) | Intent |
|--------|-------------------|--------|
| **Aggressive** | 20% above P95 | Maximize savings; accept more spike risk |
| **Conservative** | 50% above P95 | More stability during traffic spikes |

- Headroom and floors are configurable via **`RecommendationConfig`** (injected into `RightsizerEngine`).
- Default floors: `min_cpu_cores = 0.1`, `min_memory_mib = 128`.
- **Cloudability actual cost** is preferred for savings when `weekly_cost_usd` is present (`cost_status: "actual"`).
- **AWS node pricing** is used as fallback (`savings_estimation_source: "aws_node_pricing"`) when actual cost is missing.
- Savings are unavailable when neither source can estimate cost (`savings_estimation_source: "unavailable"`).

Both aggressive and conservative CPU/memory targets and savings are computed in a single engine pass and stored on each recommendation row.

---

## 5. Reporting and Notification

Reporting is a **core business workflow**: operators need a concise email summary and a path to full data.

```
Recommendations (PostgreSQL)
        ↓
   Report Generator (generate_report_summary)
        ↓
   Email Notification (format_report_email_body / MockEmailSender)
        ↓
   Recipient
        ↓
   Detailed Recommendations API
```

### Report content

Per service row:

- Current CPU requests → recommended aggressive CPU
- Current memory requests → recommended aggressive memory
- Estimated aggressive weekly savings

Summary fields: `job_id`, `total_recommendations`, `total_aggressive_estimated_savings_usd`, `report_url`.

Rows are sorted by **aggressive estimated savings descending** (highest impact first).

### Email content

- Rightsizing weekly report title and job summary
- Total recommendations and total estimated savings
- Plain-text table (one row per recommendation)
- Link to detailed report / API (`report_url`)

Example columns:

```
Namespace | Service | Current CPU | Recommended CPU | Current Memory | Recommended Memory | Estimated Savings
```

### Implementation status

| Component | Status |
|-----------|--------|
| `app/reports/report_generator.py` | **Implemented** — `ReportRow`, `ReportSummary`, `generate_report_summary()` |
| `app/reports/email_sender.py` | **Implemented** — `format_report_email_body()`, `MockEmailSender` |
| Pipeline auto-send after job | **Not wired** — call report + email explicitly or integrate in production worker |
| Production email | **Future** — AWS SES, SMTP, SendGrid, internal notification services |

---

## 6. API Endpoints

Base URL (local): `http://localhost:5000`

### `GET /api/v1/health`

Liveness check for load balancers and CI smoke tests.

### `POST /api/v1/jobs`

Creates a job (`status: pending`), enqueues Celery `run_rightsizing_job`, returns **202 Accepted** with `job_id`.

### `GET /api/v1/jobs/<job_id>`

Poll job status: `pending` | `running` | `completed` | `failed`, plus timestamps and optional `error`.

### `GET /api/v1/recommendations`

Returns persisted recommendations for a completed job.

| Query parameter | Required | Description |
|-----------------|----------|-------------|
| `job_id` | Yes | UUID of the analysis job |
| `namespace` | No | Filter by Kubernetes namespace |
| `min_aggressive_savings` | No | Minimum aggressive weekly savings (USD) |
| `page` | No | Page number (default `1`) |
| `page_size` | No | Page size (default `50`, max `200`) |

**Sorting:** `aggressive_estimated_weekly_savings_usd` descending (default).

**Response:** `job_id`, `page`, `page_size`, `total_count`, `count`, `recommendations[]`.

Example:

```bash
curl "http://localhost:5000/api/v1/recommendations?job_id=<uuid>&namespace=payments&min_aggressive_savings=10&page=1&page_size=50"
```

---

## 7. Testing

Tests use **pytest** with `pythonpath = .` (see `pytest.ini`).

### Unit tests (`tests/unit/`)

| Module | Coverage |
|--------|----------|
| `test_rightsizer.py` | RightsizerEngine, aggressive vs conservative, Cloudability cost, AWS pricing fallback, over/under-provisioned workloads, custom `RecommendationConfig` |
| `test_report_generator.py` | `ReportRow` mapping, sorting, totals, `report_url` |
| `test_email_sender.py` | Plain-text body format, `MockEmailSender` message capture |

### Integration tests (`tests/integration/`)

- Flask **test client** with **SQLite in-memory** database (`tests/conftest.py`)
- Blueprints registered: health, jobs, recommendations
- **`test_recommendations_api.py`**: filters, sorting, pagination, validation errors

Run:

```bash
pip install -r requirements.txt
pytest -v
```

**All 22 pytest tests currently pass.**

---

## 8. CI/CD and Multi-Cluster Deployment

Pipeline: `.gitlab-ci.yml`  
Cluster inventory: `deploy/clusters.yaml` (6 demo clusters: 2 dev, 2 sit, 2 prd)

### GitLab CI stages

```
test → build → smoke_test
  → deploy_dev → verify_dev → trigger_weekly_dev
  → deploy_sit → verify_sit → trigger_weekly_sit
  → deploy_prd → verify_prd → trigger_weekly_prd
```

| Stage | Purpose |
|-------|---------|
| `test` | `pytest -v` (SQLite in CI; no Docker DB) |
| `build` | Docker image build |
| `smoke_test` | Import sanity check inside container |
| `deploy_*` | Per-cluster deploy script (demo echo; commented `kubectl` for production) |
| `verify_*` | Post-deploy verification per cluster |
| `trigger_weekly_*` | Simulated weekly CronJob trigger per cluster |

### Per-cluster jobs

- **One deploy job per cluster** (e.g. `deploy_dev_us_east_1`) for GitLab UI visibility of success/failure per cluster.
- **`trigger_weekly_*`** jobs depend only on the matching **`verify_*`** job for that cluster (not all clusters in the env).

### Environment promotion

```
dev (all clusters) → sit (after dev pipeline) → prd (after sit pipeline)
```

Production may scale to **50+ clusters**; `deploy/clusters.yaml` is the inventory source for future dynamic child pipelines.

Helper scripts: `scripts/deploy_to_cluster.sh`, `scripts/verify_cluster.sh`, `scripts/trigger_weekly_job.sh`.

---

## 9. Project Structure

```
right_sizing/
├── app/
│   ├── api/
│   │   ├── health.py
│   │   ├── jobs.py
│   │   └── recommendations.py      # GET /api/v1/recommendations
│   ├── collectors/                   # K8s, Prometheus, Cloudability, AWS pricing (mock)
│   ├── engine/
│   │   └── rightsizer.py             # RightsizerEngine, RecommendationConfig
│   ├── reports/                      # Report generator + notification
│   │   ├── report_generator.py
│   │   └── email_sender.py           # MockEmailSender
│   ├── models/
│   │   └── schema.py                 # Job, Recommendation ORM
│   ├── tasks/
│   │   └── pipeline.py               # Celery run_rightsizing_job
│   └── config.py
├── tests/
│   ├── unit/                         # Engine, report, email tests
│   └── integration/                  # Recommendations API tests
├── deploy/
│   ├── clusters.yaml                 # Multi-cluster inventory
│   └── k8s/
│       └── cronjob.yaml                # Weekly Tuesday CronJob (production design)
├── scripts/
│   ├── deploy_to_cluster.sh
│   ├── verify_cluster.sh
│   └── trigger_weekly_job.sh
├── .gitlab-ci.yml
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## 10. Future Improvements

- **Real collectors** — production Prometheus, Kubernetes API, Cloudability, AWS Pricing API
- **Real email delivery** — wire report send into pipeline; SES / SMTP / SendGrid
- **Frontend report UI** — cluster, namespace, and service drill-down from email link
- **P99 metrics** — additional percentile policies
- **Confidence score** — data quality and sample-size signals per recommendation
- **HPA recommendations** — tie rightsizing to autoscaling min/max replicas
- **Dynamic child pipelines** — generate GitLab jobs from `deploy/clusters.yaml` for 50+ clusters
- **Multi-window analysis** — compare 7d / 14d / 30d P95 before recommending

---

## 11. Key Engineering Concepts Demonstrated

- **Clean Architecture** — domain engine isolated from Flask, SQLAlchemy, and collectors
- **Dependency injection** — `RecommendationConfig` and collectors passed into the engine
- **Celery asynchronous processing** — decoupled job API from long-running analysis
- **Kubernetes resource rightsizing** — requests vs P95 utilization with headroom policies
- **Cost optimization** — Cloudability actuals with AWS pricing fallback
- **REST API design** — job lifecycle, filtered/sorted/paginated recommendations
- **SQLAlchemy ORM** — relational persistence for jobs and recommendations
- **Unit testing** — pure engine and report/email formatting
- **Integration testing** — HTTP API against in-memory SQLite
- **GitLab CI/CD** — staged pipeline with per-cluster visibility
- **Multi-cluster deployment** — env promotion dev → sit → prd
- **Scheduled Kubernetes workloads** — CronJob design for weekly analysis
- **Reporting and notification systems** — summary email + detailed API for drill-down

---

## Quick Start (Demo)

```bash
docker compose up -d          # PostgreSQL, Redis, API, Celery worker
curl -X POST http://localhost:5000/api/v1/jobs
curl http://localhost:5000/api/v1/jobs/<job_id>
curl "http://localhost:5000/api/v1/recommendations?job_id=<job_id>"
```

For local development without Docker, set `DATABASE_URL` and `REDIS_URL`, run Flask and a Celery worker, then use the same API calls.

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
| Report delivery | Wired after parent job completion via `MockEmailSender` (demo) | SES, SMTP, SendGrid, or internal notification services |
| Detailed UI | `GET /api/v1/recommendations` | Frontend report page linked from email |
| CI/CD deploy | Echo scripts simulating deploy/verify/trigger | Real `kubectl` + cluster kubeconfig per job |

---

## 2. Architecture

The application follows **Clean Architecture**: the **RightsizerEngine** is pure domain logic; collectors, persistence, API, reports, and notifications are adapters around it.

### Major layers

| Layer | Responsibility |
|-------|----------------|
| **REST API** | Health, job lifecycle, recommendations query |
| **Scheduler** | Namespace discovery, whitelist/blacklist, batching (`app/scheduler/`) |
| **Celery async pipeline** | One task per namespace batch; workers run collectors → engine → PostgreSQL |
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

### Cluster-level run (production design)

A **Kubernetes CronJob** triggers one rightsizing run **per cluster**. Within the cluster, work is parallelized by **namespace batch** — not a single monolithic Celery task for the whole cluster.

```
Kubernetes CronJob (per cluster, Tuesday 08:00 UTC)
        ↓
Container: python -m app.scheduler.cluster_run
        ↓
schedule_cluster_rightsizing_run()  (env: CLUSTER_NAME, whitelist/blacklist, BATCH_SIZE)
        ↓
Namespace discovery (list_namespaces)
        ↓
Whitelist / blacklist filtering (select_namespaces)
        ↓
Namespace batching (chunk_namespaces, default 50)
        ↓
One Celery task per batch (run_rightsizing_batch_job) — parallel workers
        ↓
RightsizerEngine → PostgreSQL (shared parent job_id)
        ↓
Parent job completed when all batches finish
        ↓
Report Generator → Email Notification (cluster-level)
        ↓
GET /api/v1/recommendations
```

### Manual API trigger (demo)

**Cluster run (recommended):**

```bash
curl -X POST http://localhost:5000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"cluster": "prod-us-east-1", "blacklist": ["kube-system"], "batch_size": 50}'
```

**Legacy single-task run** (no JSON body — entire mock catalog in one worker):

```
POST /api/v1/jobs  →  run_rightsizing_job
```

1. Cluster run creates one parent `Job` with `total_batches` / `completed_batches`.
2. Each batch worker collects services only for its namespace list, runs the engine, persists rows under the same `job_id`.
3. When `completed_batches >= total_batches`, parent job status becomes `completed`.
4. Report and email remain **cluster-level** after the parent job completes.

Manifest: `deploy/k8s/cronjob.yaml` (`schedule: "0 8 * * 2"`). The CronJob container runs `python -m app.scheduler.cluster_run` — not an HTTP call to the API.

Optional: GitLab `schedule_weekly_rightsizing` can invoke `scripts/trigger_weekly_job.sh` to create a one-off Job from the CronJob template for testing; execution still happens inside the cluster.

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
Namespace | Workload | CPU Req | CPU P95 | Agg CPU | Cons CPU | Mem Req | Mem P95 | Agg Mem | Cons Mem | Savings
```

### Implementation status

| Component | Status |
|-----------|--------|
| `app/reports/report_generator.py` | **Implemented** — `ReportRow`, `ReportSummary`, `generate_report_summary()` |
| `app/reports/email_sender.py` | **Implemented** — `format_report_email_body()`, `MockEmailSender` |
| Pipeline auto-send after job | **Wired** — `_mark_batch_completed` calls `_send_completion_report` when all namespace batches finish |
| Production email | Replace `MockEmailSender` with AWS SES, SMTP, SendGrid, or an internal notification service |

---

## 6. API Endpoints

Base URL (local): `http://localhost:5000`

### `GET /api/v1/health`

Liveness check for load balancers and CI smoke tests.

### `POST /api/v1/jobs`

**Cluster run** (JSON body) — production-style namespace-batch parallelism:

```json
{
  "cluster": "prod-us-east-1",
  "whitelist": ["payments", "checkout"],
  "blacklist": ["kube-system"],
  "batch_size": 50
}
```

Creates one parent job, enqueues one `run_rightsizing_batch_job` per namespace batch, returns **202** with `job_id`, `cluster`, `total_batches`, `completed_batches`.

**Legacy run** (empty body) — single `run_rightsizing_job` for all mock services.

### `GET /api/v1/jobs/<job_id>`

Poll job status: `pending` | `running` | `completed` | `failed`, plus `cluster`, batch counters, timestamps, and optional `error`.

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
| `test_namespace_selector.py` | Whitelist, blacklist, combined filtering |
| `test_batching.py` | `chunk_namespaces` batch sizes and edge cases |
| `test_cluster_run.py` | `schedule_cluster_rightsizing_run` orchestration |
| `test_kubernetes_collector.py` | `list_namespaces`, namespace-scoped `collect_services` |
| `test_report_generator.py` | `ReportRow` mapping, sorting, totals, `report_url` |
| `test_email_sender.py` | Plain-text body format, `MockEmailSender` message capture |
| `test_pipeline_completion.py` | Report email sent once when final batch completes; no duplicate send |

### Integration tests (`tests/integration/`)

- Flask **test client** with **SQLite in-memory** database (`tests/conftest.py`)
- Blueprints registered: health, jobs, recommendations
- **`test_recommendations_api.py`**: filters, sorting, pagination, validation errors

Run:

```bash
pip install -r requirements.txt
pytest -v
```

**All 48 pytest tests currently pass.**

---

## 8. CI/CD and Multi-Cluster Deployment

Pipeline: `.gitlab-ci.yml`  
Cluster inventory: `deploy/clusters.yaml` (6 demo clusters: 2 dev, 2 sit, 2 prd)

### GitLab CI — application delivery (push / MR)

```
test → build → smoke_test → deploy_dev → verify_dev_result
```

| Stage | Purpose |
|-------|---------|
| `test` | `pytest -v` (SQLite in CI; no Docker DB) |
| `build` | Docker image build |
| `smoke_test` | Import sanity check inside container |
| `deploy_dev` | Demo deploy to `dev-us-east-1`, `dev-us-west-2` |
| `verify_dev_result` | Post-deploy verify (depends only on matching deploy job) |

### Optional GitLab helper (not the production runtime)

| Job | When |
|-----|------|
| `schedule_weekly_rightsizing` | Only when `RUN_WEEKLY_RIGHTSIZER=true` (optional Pipeline Schedule) |

This job runs `scripts/trigger_weekly_job.sh` to **manually spawn** a Kubernetes Job from the CronJob template. Production weekly runs are driven by the **in-cluster CronJob**, not GitLab.

`deploy/clusters.yaml` lists sit/prd clusters for production design; this demo pipeline omits sit/prd jobs.

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
│   ├── scheduler/                    # Namespace filter, batching, cluster orchestration
│   │   ├── namespace_selector.py
│   │   ├── batching.py
│   │   └── cluster_run.py
│   ├── engine/
│   │   └── rightsizer.py             # RightsizerEngine, RecommendationConfig
│   ├── reports/                      # Report generator + notification
│   │   ├── report_generator.py
│   │   └── email_sender.py           # MockEmailSender
│   ├── models/
│   │   └── schema.py                 # Job, Recommendation ORM
│   ├── tasks/
│   │   └── pipeline.py               # run_rightsizing_batch_job + legacy run_rightsizing_job
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

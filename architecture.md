# Kubernetes Rightsizing Recommendation Platform — Architecture Design

> Technical architecture reference for the demo implementation and production design targets.  
> Aligned with [README.md](README.md). Stack: Python · Flask · Celery · PostgreSQL · Redis · Docker Compose · GitLab CI.

**Demo vs production:** Collectors, Celery execution, and `MockEmailSender` are implemented for local/demo use. Real APIs, in-cluster workers, SES/SMTP delivery, and `kubectl`-based deploys are documented as production extensions.

---

## 1. Project Folder Structure

```
right_sizing/
├── app/
│   ├── __init__.py                 # Flask app factory
│   ├── api/
│   │   ├── health.py               # GET /api/v1/health
│   │   ├── jobs.py                 # POST/GET /api/v1/jobs
│   │   └── recommendations.py      # GET /api/v1/recommendations
│   ├── collectors/                 # K8s, Prometheus, Cloudability, AWS pricing (mock)
│   ├── scheduler/
│   │   ├── namespace_selector.py   # whitelist / blacklist
│   │   ├── batching.py             # chunk_namespaces (default 50)
│   │   └── cluster_run.py          # schedule_cluster_rightsizing_run
│   ├── engine/
│   │   └── rightsizer.py           # RightsizerEngine, RecommendationConfig
│   ├── reports/                    # Report generator + notification
│   │   ├── report_generator.py
│   │   └── email_sender.py         # MockEmailSender
│   ├── models/
│   │   └── schema.py               # Job, Recommendation ORM
│   ├── tasks/
│   │   └── pipeline.py             # run_rightsizing_batch_job + legacy run_rightsizing_job
│   └── config.py
├── tests/
│   ├── unit/                       # Engine, report, email
│   └── integration/                # Recommendations API
├── deploy/
│   ├── clusters.yaml               # Multi-cluster inventory
│   └── k8s/cronjob.yaml            # Weekly Tuesday CronJob (production design)
├── scripts/                        # deploy, verify, trigger_weekly
├── .gitlab-ci.yml
├── docker-compose.yml
└── README.md
```

**Key principle:** collectors, engine, persistence, API, reports, and notifications are decoupled — each layer can be swapped or mocked independently (Clean Architecture).

---

## 2. Main Modules

### `collectors/` — Data ingestion

Demo collectors return typed dataclasses; production implementations replace the mock classes while keeping the same interfaces.

| Collector | Output type | Data |
|-----------|-------------|------|
| `MockKubernetesCollector` | `list_namespaces()`, `ServiceSpecification` | Namespace discovery; services filtered per batch |
| `MockPrometheusCollector` | `ServiceMetrics` | `cpu_p95_cores`, `mem_p95_mib` (P95 over rolling window) |
| `MockCloudabilityCollector` | `ServiceCostInfo` | `weekly_cost_usd` (optional — never fabricated when missing) |
| `MockAwsPricingCollector` | `AwsResourcePricing` | Normalized `cpu_cost_per_core_hour`, `mem_cost_per_mib_hour` |

Correlation key: `(cluster, namespace, service_name)`.

### `engine/rightsizer.py` — Recommendation logic

Pure domain layer: no Flask, SQLAlchemy, or network I/O.

```python
class RightsizerEngine:
    def __init__(self, config: RecommendationConfig): ...

    def generate_recommendations(
        self,
        specifications: List[ServiceSpecification],
        metrics: List[ServiceMetrics],
        costs: List[ServiceCostInfo],
        pricing: Optional[AwsResourcePricing] = None,
    ) -> List[Recommendation]:
        ...
```

See **§3 Recommendation Logic** for policy details.

### `reports/` — Report generator and notification

| Module | Responsibility |
|--------|----------------|
| `report_generator.py` | `ReportRow`, `ReportSummary`, `generate_report_summary()` from ORM rows |
| `email_sender.py` | `format_report_email_body()`, `MockEmailSender` (records messages in demo) |

**Status:** Wired in `pipeline.py` — when all namespace batches complete, `_send_completion_report` uses `MockEmailSender` (demo). Production: replace with SES / SMTP / SendGrid.

### `scheduler/` — Namespace batch orchestration

| Module | Function | Role |
|--------|----------|------|
| `namespace_selector.py` | `select_namespaces()` | Whitelist (optional), then blacklist removal |
| `batching.py` | `chunk_namespaces()` | Split namespace list into batches (default 50) |
| `cluster_run.py` | `discover_namespaces()`, `schedule_cluster_rightsizing_run()` | Cluster-level parent job + enqueue batch tasks |

**Production model:** Kubernetes CronJob triggers **one cluster-level run**. Celery parallelizes **namespace batches** — not one task for the entire cluster.

### `tasks/pipeline.py` — Celery orchestration

| Task | Scope |
|------|--------|
| `run_rightsizing_batch_job(job_id, cluster, namespaces)` | One namespace batch; persists under shared parent `job_id` |
| `run_rightsizing_job(job_id)` | **Legacy** — all services in a single worker task |

Shared helper: `_execute_rightsizing_for_namespaces()` — collectors scoped to `namespaces` list.

Parent job tracks `total_batches` / `completed_batches`; status becomes `completed` when all batches finish.

### `app/__init__.py` — Flask factory

Registers blueprints: health, jobs, recommendations. Initializes SQLAlchemy.

---

## 3. Recommendation Logic

Recommendations are **P95-based**, not average-based and **not** based on fixed over-provisioning ratios (no 3× CPU / 2× memory heuristics).

### P95 usage model

- Prometheus supplies **P95 CPU and memory** over a rolling observation window (e.g. 7 days).
- Recommended request = `P95 × (1 + headroom%)`, floored at configurable minimums.
- Current Kubernetes **requests** are compared to recommendations for savings estimation.

### Aggressive vs conservative policies

Configured via **`RecommendationConfig`** (dependency-injected into `RightsizerEngine`):

| Policy | Default headroom | Intent |
|--------|------------------|--------|
| **Aggressive** | 20% | Lower target requests → higher potential savings |
| **Conservative** | 50% | Higher headroom → more spike tolerance |

Default floors: `min_cpu_cores = 0.1`, `min_memory_mib = 128`.

Both policies are computed in **one engine pass** per service:

- `aggressive_cpu_cores` / `conservative_cpu_cores`
- `aggressive_mem_mib` / `conservative_mem_mib`
- `aggressive_estimated_weekly_savings_usd` / `conservative_estimated_weekly_savings_usd`

### Cost and savings estimation

| Field | Meaning |
|-------|---------|
| `weekly_cost_usd` | **Actual** Cloudability weekly spend when present; `None` when missing (never invented) |
| `cost_status` | `"actual"` or `"missing"` |
| `savings_estimation_source` | `"cloudability"` \| `"aws_node_pricing"` \| `"unavailable"` |

**Resolution order (`_resolve_savings_context`):**

1. **Cloudability actual cost** — preferred; `cost_status = actual`, savings based on observed spend.
2. **AWS normalized node pricing fallback** — when Cloudability cost is missing but `AwsResourcePricing` is provided; derives a synthetic weekly cost from current CPU/memory requests × hourly rates × 168 hours. Used **only** for savings math, not stored as actual spend.
3. **Unavailable** — no pricing context; savings fields are `None`.

Savings estimate (`_estimate_savings`): proportional reduction from current requests to recommended CPU/memory (50% CPU weight + 50% memory weight) applied to the resolved base cost.

**Over- vs under-provisioned:** Lower recommendations than current requests → positive savings; higher recommendations → negative savings (cost increase signal).

---

## 4. Database Schema

### `jobs` — Async job lifecycle

```sql
CREATE TABLE jobs (
    id                UUID PRIMARY KEY,
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
                      -- pending | running | completed | failed
    created_at        TIMESTAMPTZ NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL,
    error             TEXT,
    cluster           VARCHAR(255),      -- cluster-level run identifier
    total_batches     INTEGER,           -- namespace batches enqueued
    completed_batches INTEGER NOT NULL DEFAULT 0
);
```

Authoritative source for job state (durable if Redis/Celery messages are lost).

### `recommendations` — One row per service per job run

```sql
CREATE TABLE recommendations (
    id              UUID PRIMARY KEY,
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,

    cluster         VARCHAR(255) NOT NULL,
    namespace       VARCHAR(255) NOT NULL,
    pod             VARCHAR(255) NOT NULL,
    container       VARCHAR(255) NOT NULL,

    -- Current state
    cpu_request_cores     NUMERIC(10,4),
    mem_request_mib         NUMERIC(10,2),
    cpu_p95_cores           NUMERIC(10,4),
    mem_p95_mib             NUMERIC(10,2),

    -- Aggressive vs conservative targets
    aggressive_cpu_cores        NUMERIC(10,4),
    conservative_cpu_cores      NUMERIC(10,4),
    aggressive_mem_mib          NUMERIC(10,2),
    conservative_mem_mib        NUMERIC(10,2),

    -- Cost (actual Cloudability only when present)
    weekly_cost_usd                         NUMERIC(10,4),
    cost_status                             VARCHAR(20) NOT NULL DEFAULT 'missing',
    savings_estimation_source               VARCHAR(30) NOT NULL DEFAULT 'unavailable',

    aggressive_estimated_weekly_savings_usd   NUMERIC(10,4),
    conservative_estimated_weekly_savings_usd NUMERIC(10,4),

    created_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_recommendations_job_id ON recommendations(job_id);
CREATE INDEX idx_recommendations_namespace ON recommendations(namespace);
```

**Legacy columns** (`rec_cpu_request_cores`, `rec_mem_request_mib`, `estimated_weekly_savings_usd`, `savings_pct`) remain nullable in ORM for backward compatibility; API and reports use aggressive/conservative fields.

**Design notes:**

- Immutable rows per job run — full audit trail, no in-place updates.
- `pod` stores engine `service_name` in the demo pipeline.
- Query latest results by `job_id`; API sorts by `aggressive_estimated_weekly_savings_usd` DESC.

### Entity relationship

```
┌─────────────┐
│    jobs     │
│ id (PK)     │
│ status      │
│ timestamps  │
│ error       │
└──────┬──────┘
       │ 1:N
       ▼
┌──────────────────────────────────────────────┐
│           recommendations                  │
│ job_id (FK)                                │
│ cluster, namespace, pod, container         │
│ current requests + P95                     │
│ aggressive_* / conservative_* targets    │
│ weekly_cost_usd, cost_status, source       │
│ aggressive/conservative savings USD      │
└──────────────────────────────────────────────┘
```

---

## 5. API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/health` | Liveness |
| `POST` | `/api/v1/jobs` | Create job, enqueue Celery task → **202** |
| `GET` | `/api/v1/jobs/<job_id>` | Poll status |
| `GET` | `/api/v1/recommendations` | List recommendations for a job |

### `GET /api/v1/recommendations`

| Query param | Required | Description |
|-------------|----------|-------------|
| `job_id` | Yes | UUID |
| `namespace` | No | Filter |
| `min_aggressive_savings` | No | Minimum aggressive weekly savings (USD) |
| `page` | No | Default `1` |
| `page_size` | No | Default `50`, max `200` |

**Sort:** `aggressive_estimated_weekly_savings_usd` descending.

**Response shape:** `job_id`, `page`, `page_size`, `total_count`, `count`, `recommendations[]` (each via `to_dict()`).

---

## 6. Celery Workflow

### Cluster-level run (production design)

```
Kubernetes CronJob (per cluster)
        │
        ▼
python -m app.scheduler.cluster_run   (CronJob container command)
        │
        ▼
schedule_cluster_rightsizing_run(cluster, whitelist?, blacklist?, batch_size=50)
        │
        ├─ Create parent Job (cluster, total_batches)
        ├─ discover_namespaces() → MockKubernetesCollector.list_namespaces()
        ├─ select_namespaces() → whitelist / blacklist
        └─ chunk_namespaces() → batches of ≤50 namespaces
        │
        ▼
For each batch: run_rightsizing_batch_job.delay(job_id, cluster, batch)
        │
        ▼ (N Celery workers in parallel)
Per batch:
        ├─ collect_services(namespaces=batch)
        ├─ collect_metrics(services)
        ├─ collect_costs(services)
        ├─ RightsizerEngine → persist recommendations (same job_id)
        └─ increment completed_batches; parent → completed when done
        │
        ▼ (cluster-level, after parent job completed)
generate_report_summary → MockEmailSender → GET /api/v1/recommendations
```

### Legacy single-task run (demo backward compatibility)

```
POST /api/v1/jobs (no JSON body)
        │
        ▼
run_rightsizing_job.delay(job_id)
        │
        ▼
collect_services() — all namespaces → engine → completed
```

**Configuration:**

- Broker / backend: Redis (`REDIS_URL`)
- `task_acks_late=True`, `worker_prefetch_multiplier=1`
- `max_retries=3` on batch and legacy tasks

**Intentionally omitted:** `job_batches` table, distributed locks, workflow engines — batch tracking uses counters on the parent `jobs` row only.

---

## 7. Data Flow

### Linear pipeline (collection → persistence)

```
Kubernetes    Prometheus    Cloudability    AWS Pricing
      │             │              │               │
      └─────────────┴──────────────┴───────────────┘
                          │
                          ▼
                    Collectors
                          │
                          ▼
                  RightsizerEngine
                          │
                          ▼
                    PostgreSQL
```

### Post-persistence branches

```
                    PostgreSQL
                    /        \
                   /          \
                  ▼            ▼
      Recommendations API    Report Generator
      (GET /api/v1/            (generate_report_summary)
       recommendations)              │
                                     ▼
                            Notification Service
                            (MockEmailSender / future SES)
                                     │
                                     ▼
                              Email Recipient
                                     │
                                     ▼
                         Detailed data via API or report_url
```

### Cluster CronJob → parallel batches

```
Kubernetes CronJob
        ↓
python -m app.scheduler.cluster_run
        ↓
schedule_cluster_rightsizing_run()
        ↓
Namespace discovery
        ↓
Namespace filtering (whitelist / blacklist)
        ↓
Namespace batching (default 50)
        ↓
Celery workers (one task per batch, parallel)
        ↓
RightsizerEngine
        ↓
PostgreSQL (single parent job_id)
        ├─► Recommendations API
        └─► Report Generator → Notification → Email Recipient
```

### Request path (manual API)

```
Client / CI
    │ POST /api/v1/jobs  {"cluster": "...", "blacklist": ["kube-system"]}
    ▼
schedule_cluster_rightsizing_run()
    │ insert parent Job + enqueue batch tasks
    ▼
Redis → multiple Celery workers (namespace batches)
    ▼
PostgreSQL ← recommendations (shared job_id)
    ├──► GET /api/v1/recommendations
    └──► Report + email (cluster-level, after job completed)
```

---

## 8. Reporting and Notification

```
PostgreSQL (recommendations)
        ↓
Report Generator — ReportRow / ReportSummary, sorted by aggressive savings DESC
        ↓
Notification Service — plain-text table + summary totals + report_url
        ↓
Email Recipient
        ↓
GET /api/v1/recommendations (full detail, filters, pagination)
```

| Email section | Content |
|---------------|---------|
| Header | Job ID, total recommendations, total aggressive estimated savings |
| Table | Namespace, service, current/recommended CPU & memory, estimated savings |
| Footer | `report_url` → detailed recommendations |

**Demo:** `MockEmailSender` appends to `sent_messages`.  
**Production:** AWS SES, SMTP, SendGrid, or internal notification platform.

---

## 9. Deployment Architecture

GitLab CI/CD orchestrates build, validation, per-environment rollout, and simulated weekly job triggers.

```
GitLab CI — application delivery (.gitlab-ci.yml)
        │
        ▼
      test → build → smoke_test
        │
        ▼
   deploy_dev → verify_dev_result (dev clusters only, demo)
        │
        ▼
   (push pipeline ends)

Kubernetes CronJob (production runtime)
   deploy/k8s/cronjob.yaml — Tuesday 08:00 UTC
        │
        ▼
   python -m app.scheduler.cluster_run
        │
        ▼
   schedule_cluster_rightsizing_run → Celery batches → PostgreSQL → report/email

Optional: GitLab schedule_weekly_rightsizing → trigger_weekly_job.sh
   (manual one-off Job from CronJob template; not the primary scheduler)
```

| Artifact | Role |
|----------|------|
| `.gitlab-ci.yml` | App delivery stages + `schedule_weekly_rightsizing` (schedule-only) |
| `deploy/clusters.yaml` | Cluster inventory (name, env, namespace, kube_context) |
| `scripts/deploy_to_cluster.sh` | Deploy hook (demo echo; commented `kubectl` for production) |
| `scripts/verify_cluster.sh` | Post-deploy verification |
| `scripts/trigger_weekly_job.sh` | Manual kubectl helper to spawn a Job from CronJob (optional CI) |

See **§10 Multi-Cluster Deployment** for cluster-level job layout.

---

## 10. Multi-Cluster Deployment

**Inventory:** `deploy/clusters.yaml` lists clusters by environment:

| Environment | Demo clusters |
|-------------|---------------|
| `dev` | `dev-us-east-1`, `dev-us-west-2` |
| `sit` | `sit-us-east-1`, `sit-us-west-2` |
| `prd` | `prd-us-east-1`, `prd-us-west-2` |

### Demo CI scope (dev only)

Push pipelines deploy and verify **dev-us-east-1** and **dev-us-west-2** only. Weekly rightsizing runs via the **in-cluster CronJob** (`python -m app.scheduler.cluster_run`), not as part of every code push.

### Environment promotion (production design)

Full **dev → sit → prd** rollout and per-cluster jobs are documented in `deploy/clusters.yaml` but omitted from this demo `.gitlab-ci.yml` to keep the pipeline interview-friendly.

### Scale: 50+ clusters

Production often has **50+ clusters** across regions and accounts. This demo uses six static jobs. At scale, teams typically:

- Generate **dynamic child pipelines** from `deploy/clusters.yaml` (GitLab `trigger` + matrix or YAML-driven job generation), or
- Partition by env/region with separate pipeline includes.

Future improvement documented in README §10.

---

## 11. Testing Strategy

### Unit tests (`tests/unit/`)

| File | Focus |
|------|--------|
| `test_rightsizer.py` | P95 headroom, aggressive vs conservative, Cloudability vs AWS fallback, over/under-provisioned, custom config |
| `test_namespace_selector.py` | Whitelist, blacklist, combined filters |
| `test_batching.py` | Batch sizes, empty input, invalid `batch_size` |
| `test_cluster_run.py` | Parent job creation, batch enqueue, empty filter completion |
| `test_kubernetes_collector.py` | `list_namespaces`, namespace-scoped collection |
| `test_report_generator.py` | `generate_report_summary`, sorting, totals |
| `test_email_sender.py` | Plain-text body, `MockEmailSender` |

Engine tests use **no database and no network** — highest coverage, fastest feedback.

### Integration tests (`tests/integration/`)

- Flask **test client** + **SQLite in-memory** (`tests/conftest.py`)
- Blueprints: health, jobs, recommendations
- `test_recommendations_api.py` — filters, `min_aggressive_savings`, sort, pagination, validation

**All 43 pytest tests pass.** CI runs `pytest -v` in the `test` stage with `SQLALCHEMY_DATABASE_URI=sqlite:///:memory:`.

### Principles

- Business logic in engine and report formatters — unit tested
- API tests validate HTTP contract and query behavior
- Collectors tested implicitly via pipeline/engine inputs (mock data shape is stable dataclasses)

---

## 12. Docker Compose Services

| Service | Role |
|---------|------|
| `web` | Flask API on port 5000 |
| `worker` | Celery worker (`app.tasks.pipeline`) |
| `db` | PostgreSQL 16 |
| `redis` | Celery broker and result backend |

Startup: `docker compose up --build`

---

## 13. Design Tradeoffs

### Async Celery jobs vs synchronous API

**Chose:** POST returns 202; worker runs multi-source collection and engine.  
**Why:** Production analysis can take minutes; job table enables retry and audit.  
**Tradeoff:** Requires broker, worker, and polling.

### Immutable recommendation rows

**Chose:** Insert-only per job run.  
**Why:** History, simple worker, clear “latest” semantics via `job_id`.  
**Tradeoff:** Growth over time — archival/TTL in production.

### Pure RightsizerEngine

**Chose:** No I/O inside engine.  
**Why:** Trivial unit tests; side effects in Celery and API layers.  
**Tradeoff:** `pipeline.py` owns orchestration and mapping to ORM.

### Report/email outside Celery task (demo)

**Chose:** Separate `app/reports` modules, manual or future hook after commit.  
**Why:** Clear separation of analysis vs delivery; easy to test email format.  
**Tradeoff:** Production should invoke send in worker or event handler to avoid missed notifications.

### Namespace-batch parallelism (no workflow engine)

**Chose:** Parent `jobs` row + `total_batches` / `completed_batches` counters; one Celery task per namespace batch.  
**Why:** Matches production CronJob-per-cluster model; scales to hundreds of namespaces across workers without a monolithic task.  
**Tradeoff:** Concurrent batch completion uses simple counter increment (demo); production may want atomic SQL `UPDATE ... RETURNING` for strict correctness.

### Redis broker + PostgreSQL job state

**Chose:** Redis for queue; PostgreSQL for authoritative job/recommendation data.  
**Why:** Simple demo setup.  
**Tradeoff:** Redis restart can drop queued tasks; job row remains recoverable for status.

---

## 14. Future Production Extensions

| Concern | Demo | Production |
|---------|------|------------|
| Collectors | Mock dataclasses | Real Prometheus, K8s API, Cloudability, AWS Pricing API |
| Scheduling | Manual POST + CI `trigger_weekly_*` | `deploy/k8s/cronjob.yaml` per cluster |
| Email | `MockEmailSender` | SES, SMTP, SendGrid |
| UI | Recommendations API only | Frontend linked from `report_url` |
| CI deploy | Shell echo | Real `kubectl` with per-cluster kubeconfig |
| Multi-cluster | 6 static GitLab jobs | Dynamic child pipelines from `clusters.yaml` |
| Metrics | P95 only | P99, multi-window (7d/14d/30d), confidence scores |
| Autoscaling | — | HPA min/max recommendations |

---

*Architecture document scoped for technical review and interview walkthrough. For quick start and API examples, see [README.md](README.md).*

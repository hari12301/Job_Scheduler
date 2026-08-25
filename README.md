# Distributed Job Scheduling & Background Execution Platform

A production-inspired, fault-tolerant distributed job scheduling platform built with **Python**, **Django 5**, **Django REST Framework**, **PostgreSQL**, and a modern **JavaScript / CSS Web Dashboard**.

---

## 🏛️ System Architecture

```
                                  +---------------------------------------+
                                  |         Web Dashboard UI              |
                                  |   (Chart.js, Live Metrics, Logs)      |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +-------------------+-------------------+
                                  |      Django REST Framework APIs       |
                                  |   (Auth, Queues, Jobs, DLQ, Metrics)  |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |       PostgreSQL Database Engine      |
                                  |   (ACID, SELECT FOR UPDATE SKIP LOCKED|
                                  |    Advisory Locks, Time-series logs)  |
                                  +-------+--------------------+----------+
                                          |                    |
                     +--------------------+                    +--------------------+
                     v                                                              v
            +-------------------------------+                             +-------------------------------+
            |    Distributed Workers (N)    |                             |      Scheduler & Reaper       |
            | - Multi-threaded Worker Pool  |                             | - Cron / Schedule Evaluator   |
            | - Atomic Claim Engine         |                             | - DAG Dependency Resolver     |
            | - Heartbeat & Telemetry       |                             | - Zombie Worker Reaper        |
            | - Execution Sandboxes         |                             | - Dead-Letter Queue Manager   |
            | - Graceful Shutdown (SIGTERM) |                             | - Rate Limiter (Token Bucket) |
            +-------------------------------+                             +-------------------------------+
```

---

## 📊 Database Design & Relational Schema

The database schema is strictly normalized and indexed for high-throughput concurrency:

| Table | Primary Key | Foreign Keys / Relations | Purpose & Indexes |
| :--- | :--- | :--- | :--- |
| **`organizations`** | `id` (UUID) | - | Multi-tenant organization boundaries. Unique `slug`. |
| **`projects`** | `id` (UUID) | `organization_id` -> `organizations` (CASCADE) | Workspace container for queues, retry policies, and API keys. |
| **`project_memberships`**| `id` (UUID) | `user_id` -> `auth_user`, `project_id` -> `projects` | RBAC roles (`ADMIN`, `DEVELOPER`, `VIEWER`). |
| **`api_keys`** | `id` (UUID) | `project_id` -> `projects` (CASCADE) | SHA-256 hashed API token authentication (`X-API-Key`). |
| **`retry_policies`** | `id` (UUID) | `project_id` -> `projects` (CASCADE) | Reusable retry strategies (`FIXED`, `LINEAR_BACKOFF`, `EXPONENTIAL_BACKOFF`, `jitter`). |
| **`queues`** | `id` (UUID) | `project_id` -> `projects`, `default_retry_policy_id` | Queue configuration with priority (1-100), concurrency limit, and rate limits. |
| **`jobs`** | `id` (UUID) | `project_id`, `queue_id`, `claimed_by_worker_id`, `retry_policy_id`, `parent_job_id` | Core job entities. Compound index on `(queue_id, status, priority DESC, scheduled_at ASC)`. |
| **`job_dependencies`**| `id` (UUID) | `job_id` -> `jobs`, `depends_on_id` -> `jobs` | Directed Acyclic Graph (DAG) workflow dependencies. |
| **`job_executions`** | `id` (UUID) | `job_id` -> `jobs`, `worker_id` -> `workers` | Immutable audit log of every execution attempt and timing metrics. |
| **`job_logs`** | `id` (BigInt)| `job_id` -> `jobs`, `execution_id` -> `job_executions`| Streaming log messages (`INFO`, `WARN`, `ERROR`, `DEBUG`) and timestamps. |
| **`scheduled_jobs`** | `id` (UUID) | `project_id`, `queue_id` | Recurring cron jobs with standard 5-part cron expressions (`* * * * *`). |
| **`workers`** | `id` (UUID) | - | Worker node registry, CPU/Memory telemetry, status, and heartbeat timestamps. |
| **`worker_heartbeats`**| `id` (BigInt)| `worker_id` -> `workers` (CASCADE) | Time-series telemetry snapshots. |
| **`dead_letter_queue_entries`** | `id` (UUID)| `job_id` -> `jobs` (1:1), `original_queue_id` | Fatal failure inspection with automated AI root-cause diagnosis. |
| **`distributed_locks`** | `lock_key` (PK)| - | Distributed locking with TTL expiration. |
| **`rate_limit_buckets`**| `queue_id` (PK)| `queue_id` -> `queues` (1:1) | Token bucket state for queue-level rate limiting. |

---

## ⚡ Concurrency & Atomic Claim Engine

### PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED`
To avoid race conditions and double executions when multiple worker processes poll the same queue simultaneously, the claimer executes atomic locking:

```sql
SELECT id FROM jobs
WHERE queue_id = %s
  AND status = 'QUEUED'
  AND scheduled_at <= NOW()
ORDER BY priority DESC, scheduled_at ASC
LIMIT %s
FOR UPDATE SKIP LOCKED;
```

**Key Advantages:**
1. **Zero Lock Contention**: Workers skip rows locked by other workers without blocking or waiting.
2. **Strict Priority Processing**: Highest priority jobs (`priority DESC`) are claimed first.
3. **Queue Concurrency & Rate Limit Enforced**: Claimer evaluates active running jobs against `queue.concurrency_limit` and checks the token bucket before dispatching.

---

## 🔄 Complete Job Lifecycle State Machine

```
              +-------------+
              |   PENDING   | (DAG Dependencies Unmet)
              +------+------+
                     | (All Upstream Parents COMPLETED)
                     v
+-------------+      +-------------+      +-------------+
|   DELAYED   | ---> |   QUEUED    | ---> |   CLAIMED   |
| (scheduled) |      +-------------+      +------+------+
+-------------+                                  |
                                                 v
+-------------+      +-------------+      +-------------+
|  COMPLETED  | <--- |   RUNNING   | ---> |   FAILED    |
+-------------+      +-------------+      +------+------+
                                                 |
                     +-------------+             | (Attempt < max_retries)
                     |  RETRYING   | <-----------+
                     +------+------+
                            | (Backoff delay elapsed)
                            v
                     +-------------+
                     |   QUEUED    |
                     +-------------+
                            |
                            | (Attempt >= max_retries)
                            v
                     +----------------------------+
                     | DEAD_LETTER (Moved to DLQ) |
                     +----------------------------+
```

---

## 🚀 Key Features

1. **Multi-Type Job Scheduling**:
   - **Immediate Jobs**: Executed as soon as worker capacity is available.
   - **Delayed / Scheduled Jobs**: Activated when `scheduled_at <= NOW()`.
   - **Recurring (Cron) Jobs**: Evaluated continuously with standard 5-part cron syntax (`*/5 * * * *`).
   - **Batch Jobs**: Enqueued atomically with a shared `batch_id`.
   - **DAG Workflows**: Dependency graphs where child jobs trigger only when parent jobs complete.
2. **Fault Tolerance & Reliability**:
   - Configurable retry strategies: `Fixed`, `Linear Backoff`, `Exponential Backoff`, and `Jitter`.
   - **Dead Letter Queue (DLQ)**: Captures permanent failures with automated AI root-cause analysis.
   - **Zombie Worker Reaper**: Detects crashed workers (>30s stale heartbeats) and safely reclaims in-flight jobs.
   - **Graceful Shutdown**: Workers finish in-flight jobs upon `SIGINT`/`SIGTERM` before terminating.
3. **Rich Web Dashboard**:
   - **Overview**: Real-time throughput graphs, success/failure donuts, and queue health meters.
   - **Queue Manager**: Interactive pause/resume, concurrency limits, and queue purging.
   - **Job Explorer**: Status filter, search by ID or idempotency key, pagination, and live auto-refresh.
   - **Job Inspector**: Live streaming terminal logs, retry history table, JSON payloads, and execution metrics.
   - **DAG Visualizer**: Interactive node graph rendering step dependencies and live statuses.
   - **DLQ Center**: One-click single and bulk job replay.
   - **Worker Fleet**: CPU/Memory telemetry gauges and heartbeat health monitoring.
4. **REST API & Interactive OpenAPI Docs**:
   - Full Swagger UI (`/api/docs/`) and Redoc (`/api/redoc/`).

---

## 🛠️ Quickstart & Local Setup

### Option 1: Docker Compose (Recommended)
```bash
docker-compose up --build
```
This automatically boots:
- PostgreSQL 16 on port `5432`
- Django Web Dashboard & API on `http://localhost:8000`
- Distributed Worker Daemon
- Central Scheduler & Reaper Daemon

### Option 2: Local Python Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Migrations & Seed Demo Data**:
   ```bash
   python manage.py migrate
   python manage.py seed_demo
   ```

3. **Start the Web Dashboard**:
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```

4. **Start the Distributed Worker Daemon**:
   ```bash
   python manage.py run_worker --concurrency=4
   ```

5. **Start the Central Scheduler & Reaper**:
   ```bash
   python manage.py run_scheduler --tick-interval=2.0
   ```

6. **(Optional) Simulate Live Traffic**:
   ```bash
   python manage.py simulate_traffic --interval=1.0
   ```

---

## 🧪 Running Automated Tests

Run the full Django test suite testing atomic claim concurrency, retry policies, DAG resolutions, API endpoints, and rate limits:

```bash
python manage.py test
```

---

## 📡 REST API Summary

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET/POST` | `/api/v1/queues/` | List and create queues |
| `POST` | `/api/v1/queues/{id}/pause/` | Pause job queue processing |
| `POST` | `/api/v1/queues/{id}/resume/` | Resume job queue processing |
| `POST` | `/api/v1/queues/{id}/purge/` | Purge pending jobs from queue |
| `GET/POST` | `/api/v1/jobs/` | List (with filters) and enqueue jobs |
| `POST` | `/api/v1/jobs/batch/` | Enqueue batch of jobs atomically |
| `POST` | `/api/v1/jobs/{id}/retry/` | Manually retry a failed/dead job |
| `POST` | `/api/v1/jobs/{id}/cancel/` | Cancel an in-flight or queued job |
| `GET` | `/api/v1/jobs/{id}/logs/` | Streaming logs for job |
| `POST` | `/api/v1/workflows/` | Create multi-step DAG workflow |
| `GET` | `/api/v1/workflows/batch/{id}/` | Get DAG graph topology and node states |
| `GET/POST` | `/api/v1/schedules/` | Manage recurring cron schedules |
| `POST` | `/api/v1/schedules/{id}/trigger_now/` | Trigger cron job immediately |
| `GET/POST` | `/api/v1/dlq/` | Inspect Dead Letter Queue entries |
| `POST` | `/api/v1/dlq/{id}/replay/` | Replay specific dead letter job |
| `POST` | `/api/v1/dlq/replay_all/` | Replay all dead letter jobs |
| `GET` | `/api/v1/metrics/` | Aggregated realtime telemetry and latency |
| `GET` | `/api/docs/` | Interactive Swagger API documentation |


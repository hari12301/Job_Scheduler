# Job Scheduler


---

## 🚀 Quick Start Guide (How to Run This Project)

### Option 1: Run with Docker Compose (Fastest — Zero Setup)
```bash
# Extract the zip file, open terminal in this folder, and run:
docker-compose up --build
```
> This automatically starts **PostgreSQL**, runs database migrations, seeds realistic demo data (`seed_demo`), launches the **Web Dashboard** at `http://localhost:8000/`, and starts the background **Worker Daemon** and **Scheduler Daemon**.

---

### Option 2: Run with Local Python & PostgreSQL

#### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 2. Configure Database Credentials (if needed)
In `scheduler_project/settings.py` (lines 80-85), set your PostgreSQL password (default is `postgres`):
```python
DB_PASSWORD = os.environ.get('POSTGRES_PASSWORD', 'your_postgres_password')
```

#### 3. Run Migrations & Seed Demo Data
```bash
python manage.py migrate
python manage.py seed_demo
```

#### 4. Start the Web Dashboard
```bash
python manage.py runserver 0.0.0.0:8000
```
Open **`http://localhost:8000/`** in your browser!

#### 5. Start the Background Worker Daemon (in a separate terminal)
```bash
python manage.py run_worker --concurrency=4
```

#### 6. Start the Central Scheduler & Reaper (in a separate terminal)
```bash
python manage.py run_scheduler --tick-interval=2.0
```

> 💡 **Windows 1-Click Launcher**: On Windows, you can simply double-click **`start_all.bat`** to start the web dashboard, worker daemon, and scheduler all at once!

---

### 🧪 How to Run Automated Tests
Run the full concurrency and unit test suite:
```bash
python manage.py test
```

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

## 📊 Database Design & Relational Schema (ER Model)

| Table | Primary Key | Foreign Keys / Relations | Description & Indexes |
| :--- | :--- | :--- | :--- |
| **`organizations`** | `id` (UUID) | - | Multi-tenant organization boundaries. Unique `slug`. |
| **`projects`** | `id` (UUID) | `organization_id` -> `organizations` | Workspace container for queues, retry policies, and API keys. |
| **`project_memberships`**| `id` (UUID) | `user_id` -> `auth_user`, `project_id` -> `projects` | Role-Based Access Control (`ADMIN`, `DEVELOPER`, `VIEWER`). |
| **`api_keys`** | `id` (UUID) | `project_id` -> `projects` | Secure SHA-256 hashed API token authentication (`X-API-Key`). |
| **`retry_policies`** | `id` (UUID) | `project_id` -> `projects` | Reusable retry strategies (`FIXED`, `LINEAR_BACKOFF`, `EXPONENTIAL_BACKOFF`, `jitter`). |
| **`queues`** | `id` (UUID) | `project_id` -> `projects`, `default_retry_policy_id` | Queue configuration with priority (1-100), concurrency limit, and rate limits. |
| **`jobs`** | `id` (UUID) | `project_id`, `queue_id`, `claimed_by_worker_id`, `retry_policy_id`, `parent_job_id` | Core job entity. Compound index on `(queue_id, status, priority DESC, scheduled_at ASC)`. |
| **`job_dependencies`**| `id` (UUID) | `job_id` -> `jobs`, `depends_on_id` -> `jobs` | Directed Acyclic Graph (DAG) workflow step dependencies. |
| **`job_executions`** | `id` (UUID) | `job_id` -> `jobs`, `worker_id` -> `workers` | Immutable audit log of every execution attempt and timing metrics. |
| **`job_logs`** | `id` (BigInt)| `job_id` -> `jobs`, `execution_id` -> `job_executions`| Streaming log messages (`INFO`, `WARN`, `ERROR`, `DEBUG`) and timestamps. |
| **`scheduled_jobs`** | `id` (UUID) | `project_id`, `queue_id` | Recurring cron jobs with standard 5-part cron expressions (`* * * * *`). |
| **`workers`** | `id` (UUID) | - | Worker node registry, CPU/Memory telemetry, status, and heartbeat timestamps. |
| **`worker_heartbeats`**| `id` (BigInt)| `worker_id` -> `workers` | Time-series telemetry snapshots. |
| **`dead_letter_queue_entries`** | `id` (UUID)| `job_id` -> `jobs` (1:1), `original_queue_id` | Fatal failure inspection with automated AI root-cause diagnosis. |
| **`distributed_locks`** | `lock_key` (PK)| - | Distributed locking with TTL expiration. |
| **`rate_limit_buckets`**| `queue_id` (PK)| `queue_id` -> `queues` (1:1) | Token bucket state for queue-level rate limiting. |

---

## ⚡ Concurrency Strategy: Atomic `SELECT ... FOR UPDATE SKIP LOCKED`

To prevent duplicate execution and race conditions across multiple distributed workers polling the same database queue simultaneously, the claimer executes atomic row-locking:

```sql
SELECT id FROM jobs
WHERE queue_id = %s
  AND status = 'QUEUED'
  AND scheduled_at <= NOW()
ORDER BY priority DESC, scheduled_at ASC
LIMIT %s
FOR UPDATE SKIP LOCKED;
```

**Key Architectural Benefits:**
1. **Zero Lock Contention**: Workers skip rows locked by other workers without blocking or waiting.
2. **Strict Priority Processing**: Highest priority jobs (`priority DESC`) are claimed first.
3. **Capacity Enforced**: Claimer evaluates active running jobs against `queue.concurrency_limit` and checks the token bucket rate limiter before dispatching.

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

## ⚖️ Design Decisions & Trade-Offs

1. **PostgreSQL Row-Locking (`SKIP LOCKED`) vs. Dedicated Message Brokers (Redis/RabbitMQ)**:
   - *Decision*: Used PostgreSQL as the queue backend.
   - *Trade-off*: Eliminates the operational overhead of running and synchronizing a secondary message broker. Guarantees ACID transactional consistency, zero data loss, and atomic state updates between jobs and application data.
2. **Exponential Backoff with Jitter**:
   - *Decision*: Applied randomized jitter (+/- 15%) to exponential retry intervals.
   - *Trade-off*: Prevents the "Thundering Herd" problem where multiple retrying jobs hit a recovering downstream service at the exact same second.
3. **Heartbeat-Based Dead Worker Reaping**:
   - *Decision*: Workers send heartbeats every 5 seconds; scheduler reclaims jobs if heartbeat is older than 30 seconds.
   - *Trade-off*: Guarantees "at-least-once" execution even if a worker server encounters an out-of-memory error (OOM) or abrupt kernel termination.

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

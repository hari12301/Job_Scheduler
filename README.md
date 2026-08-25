# Distributed Job Scheduling & Background Execution Platform

A production-grade, fault-tolerant distributed background job scheduling and execution platform built with **Python**, **Django 5**, **Django REST Framework**, **PostgreSQL**, and a modern **Web Dashboard**.

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

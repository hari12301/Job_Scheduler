import time
import json
import logging
import traceback
import requests
from django.utils import timezone
from core.models import Job, JobExecution, JobLog, DeadLetterQueueEntry, Worker
from core.engine.retry import calculate_next_retry
from core.engine.ai_summarizer import generate_ai_failure_summary
from core.engine.dag_engine import resolve_workflow_dependencies

logger = logging.getLogger(__name__)

# Registry of built-in job execution handlers
HANDLER_REGISTRY = {}

def register_handler(name):
    def decorator(fn):
        HANDLER_REGISTRY[name] = fn
        return fn
    return decorator


@register_handler('mock_task')
def handle_mock_task(payload, log_fn):
    log_fn("INFO", "Starting mock task execution...")
    duration = payload.get('duration_seconds', 1.0)
    fail_rate = payload.get('fail_rate', 0.0)
    error_type = payload.get('error_type', 'exception')

    log_fn("INFO", f"Simulating workload for {duration} seconds (fail_rate={fail_rate})")
    time.sleep(min(duration, 10))

    import random
    if random.random() < fail_rate:
        if error_type == 'timeout':
            log_fn("ERROR", "Operation timed out waiting for downstream resource")
            raise TimeoutError("Upstream socket read timeout after 30000ms")
        elif error_type == 'connection':
            log_fn("ERROR", "Database connection pool exhausted")
            raise ConnectionError("ConnectionRefusedError: [Errno 111] Connection refused on port 5432")
        elif error_type == 'schema':
            log_fn("ERROR", "Invalid payload key encountered")
            raise KeyError("Payload missing required key 'customer_uuid'")
        else:
            log_fn("ERROR", "Simulation trigger: synthetic exception thrown")
            raise RuntimeError(f"Synthetic failure simulation in mock_task: {payload.get('error_msg', 'Task failed')}")

    log_fn("INFO", "Mock task computations completed successfully.")
    return {
        "status": "success",
        "processed_items": payload.get("items_count", 42),
        "checksum": "a8fbc73901b"
    }


@register_handler('http_request')
def handle_http_request(payload, log_fn):
    url = payload.get('url')
    if not url:
        raise ValueError("Missing required 'url' parameter in HTTP job payload.")

    method = payload.get('method', 'GET').upper()
    headers = payload.get('headers', {})
    body = payload.get('body', {})
    timeout = payload.get('timeout', 15)

    log_fn("INFO", f"Dispatching HTTP {method} request to {url}")
    if method == 'GET':
        res = requests.get(url, headers=headers, timeout=timeout)
    elif method == 'POST':
        res = requests.post(url, json=body, headers=headers, timeout=timeout)
    elif method == 'PUT':
        res = requests.put(url, json=body, headers=headers, timeout=timeout)
    elif method == 'DELETE':
        res = requests.delete(url, headers=headers, timeout=timeout)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    log_fn("INFO", f"HTTP response received with status code: {res.status_code}")
    res.raise_for_status()

    try:
        data = res.json()
    except Exception:
        data = res.text[:1000]

    return {"status_code": res.status_code, "data": data}


@register_handler('email_dispatch')
def handle_email_dispatch(payload, log_fn):
    to_email = payload.get('to')
    subject = payload.get('subject', 'Notification')
    template = payload.get('template', 'default')

    log_fn("INFO", f"Preparing email dispatch to: {to_email}")
    log_fn("INFO", f"Rendering email template '{template}' with subject: '{subject}'")
    time.sleep(0.5)
    log_fn("INFO", f"Message accepted by SMTP relay. Message ID: <msg_{int(time.time())}@scheduler.internal>")

    return {
        "dispatched": True,
        "recipient": to_email,
        "timestamp": timezone.now().isoformat()
    }


@register_handler('data_pipeline')
def handle_data_pipeline(payload, log_fn):
    dataset_name = payload.get('dataset', 'analytics_events')
    batch_size = payload.get('batch_size', 500)

    log_fn("INFO", f"Ingesting batch stream for dataset: '{dataset_name}'")
    log_fn("INFO", f"Validating schema constraints for {batch_size} records...")
    time.sleep(0.8)
    log_fn("INFO", "Running deduplication and anomaly filtering...")
    time.sleep(0.4)
    log_fn("INFO", f"Successfully synced {batch_size} rows to destination warehouse.")

    return {
        "dataset": dataset_name,
        "records_ingested": batch_size,
        "records_rejected": 0,
        "duration_ms": 1200
    }


def execute_job(job: Job, worker: Worker = None):
    """
    Executes a single claimed job, logs all steps, updates attempts,
    handles retries and routes fatal errors to the Dead Letter Queue.
    """
    now = timezone.now()

    # Transition to RUNNING
    job.status = Job.Status.RUNNING
    job.started_at = now
    job.current_attempt += 1
    job.save(update_fields=['status', 'started_at', 'current_attempt'])

    # Create Execution Record
    execution = JobExecution.objects.create(
        job=job,
        worker=worker,
        attempt_number=job.current_attempt,
        status=JobExecution.ExecutionStatus.RUNNING,
        started_at=now
    )

    def log_message(level, message, metadata=None):
        JobLog.objects.create(
            job=job,
            execution=execution,
            level=level,
            message=message,
            metadata=metadata or {}
        )

    log_message("INFO", f"Job picked up by worker {worker.hostname if worker else 'Standalone'}. Attempt #{job.current_attempt} of {job.max_retries}")

    start_perf = time.perf_counter()
    handler_fn = HANDLER_REGISTRY.get(job.handler, handle_mock_task)

    try:
        # Execute Handler
        result = handler_fn(job.payload, log_message)
        end_perf = time.perf_counter()
        duration_ms = int((end_perf - start_perf) * 1000)

        # Mark execution as COMPLETED
        finished_now = timezone.now()
        execution.status = JobExecution.ExecutionStatus.COMPLETED
        execution.finished_at = finished_now
        execution.duration_ms = duration_ms
        execution.save(update_fields=['status', 'finished_at', 'duration_ms'])

        # Mark Job as COMPLETED
        job.status = Job.Status.COMPLETED
        job.result = result
        job.completed_at = finished_now
        job.error_message = None
        job.error_stack = None
        job.save(update_fields=['status', 'result', 'completed_at', 'error_message', 'error_stack'])

        log_message("INFO", f"Job completed successfully in {duration_ms}ms.", {"result": result})

        # Check DAG dependencies
        resolve_workflow_dependencies()

        return True, result

    except Exception as exc:
        end_perf = time.perf_counter()
        duration_ms = int((end_perf - start_perf) * 1000)
        finished_now = timezone.now()
        error_str = str(exc)
        stack_str = traceback.format_exc()

        log_message("ERROR", f"Execution failed: {error_str}", {"stack_trace": stack_str})

        execution.status = JobExecution.ExecutionStatus.FAILED
        execution.finished_at = finished_now
        execution.duration_ms = duration_ms
        execution.error_message = error_str
        execution.error_stack = stack_str
        execution.exit_code = 1
        execution.save(update_fields=['status', 'finished_at', 'duration_ms', 'error_message', 'error_stack', 'exit_code'])

        job.error_message = error_str
        job.error_stack = stack_str

        # Check Retry Policy
        if job.current_attempt < job.max_retries:
            next_run = calculate_next_retry(job)
            job.status = Job.Status.QUEUED  # Or RETRYING, ready at scheduled_at
            job.scheduled_at = next_run
            job.claimed_by_worker = None
            job.claimed_at = None
            job.save(update_fields=['status', 'scheduled_at', 'error_message', 'error_stack', 'claimed_by_worker', 'claimed_at'])
            log_message("WARN", f"Job will be retried (attempt #{job.current_attempt + 1}) at {next_run.isoformat()}")
        else:
            # Retries Exhausted -> Dead Letter Queue
            job.status = Job.Status.DEAD_LETTER
            job.completed_at = finished_now
            job.save(update_fields=['status', 'completed_at', 'error_message', 'error_stack'])

            category, ai_summary = generate_ai_failure_summary(job.name, error_str, stack_str)
            DeadLetterQueueEntry.objects.update_or_create(
                job=job,
                defaults={
                    'original_queue': job.queue,
                    'failure_reason': error_str,
                    'failure_category': category,
                    'ai_summary': ai_summary
                }
            )
            log_message("ERROR", f"Job exhausted all {job.max_retries} attempts. Moved to Dead Letter Queue (DLQ). Category: {category}")

            # Trigger DAG cascade check
            resolve_workflow_dependencies()

        return False, error_str


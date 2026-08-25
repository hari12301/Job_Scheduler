import os
import sys
import time
import socket
import signal
import logging
from concurrent.futures import ThreadPoolExecutor
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Worker, WorkerHeartbeat, Job
from core.engine.claimer import claim_jobs_for_worker
from core.engine.executor import execute_job

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Runs a distributed background job worker process."

    def add_arguments(self, parser):
        parser.add_argument('--concurrency', type=int, default=4, help='Number of concurrent worker threads.')
        parser.add_argument('--queues', type=str, default='', help='Comma-separated queue names to subscribe to (default: all).')
        parser.add_argument('--poll-interval', type=float, default=1.0, help='Polling interval in seconds when queues are empty.')
        parser.add_argument('--once', action='store_true', help='Run a single polling cycle and exit (useful for testing).')

    def handle(self, *args, **options):
        concurrency = options['concurrency']
        queue_names = [q.strip() for q in options['queues'].split(',') if q.strip()]
        poll_interval = options['poll_interval']
        run_once = options['once']

        hostname = socket.gethostname()
        pid = os.getpid()

        self.stdout.write(self.style.SUCCESS(
            f"🚀 Initializing Distributed Worker Daemon [Host: {hostname}, PID: {pid}, Concurrency: {concurrency}]"
        ))

        # Register Worker Node in Database
        worker = Worker.objects.create(
            hostname=hostname,
            pid=pid,
            status=Worker.Status.ACTIVE,
            concurrency=concurrency,
            queues_subscribed=queue_names,
            started_at=timezone.now(),
            last_heartbeat_at=timezone.now()
        )

        self.worker_id = worker.id
        self.running = True
        self.active_jobs = 0

        # Setup Signal Handlers for Graceful Shutdown
        def signal_handler(signum, frame):
            self.stdout.write(self.style.WARNING("\n🛑 Received termination signal. Initiating graceful shutdown..."))
            self.running = False

        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except Exception:
            pass  # Windows or non-main thread fallback

        executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix=f"Worker-{str(worker.id)[:6]}")
        last_heartbeat_time = time.time()

        try:
            while self.running:
                # 1. BroadCast Heartbeat
                now_sec = time.time()
                if now_sec - last_heartbeat_time >= 5.0:
                    self.send_heartbeat(worker)
                    last_heartbeat_time = now_sec

                # 2. Calculate available worker slots
                available_slots = concurrency - self.active_jobs
                if available_slots > 0:
                    claimed_jobs = claim_jobs_for_worker(
                        worker=worker,
                        queue_names=queue_names if queue_names else None,
                        limit=available_slots
                    )

                    for job in claimed_jobs:
                        self.active_jobs += 1
                        self.stdout.write(self.style.HTTP_INFO(f"⚡ Claimed Job-{str(job.id)[:8]} ({job.name}) on Queue [{job.queue.name}]"))
                        executor.submit(self._run_job_wrapper, job, worker)

                    if not claimed_jobs:
                        time.sleep(poll_interval)
                else:
                    time.sleep(0.5)

                if run_once:
                    break

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Interrupted by user."))
        finally:
            self.stdout.write(self.style.NOTICE("Waiting for in-flight tasks to complete..."))
            executor.shutdown(wait=True)
            self.deregister_worker(worker)
            self.stdout.write(self.style.SUCCESS("✅ Worker daemon gracefully stopped."))

    def _run_job_wrapper(self, job: Job, worker: Worker):
        try:
            execute_job(job, worker)
        except Exception as e:
            logger.error(f"Fatal error executing job {job.id}: {e}", exc_info=True)
        finally:
            self.active_jobs = max(0, self.active_jobs - 1)

    def send_heartbeat(self, worker: Worker):
        try:
            now = timezone.now()
            worker.last_heartbeat_at = now
            worker.current_running_jobs = self.active_jobs
            # Update system metrics if available
            worker.save(update_fields=['last_heartbeat_at', 'current_running_jobs'])

            WorkerHeartbeat.objects.create(
                worker=worker,
                running_job_count=self.active_jobs
            )
        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")

    def deregister_worker(self, worker: Worker):
        try:
            worker.status = Worker.Status.DEAD
            worker.current_running_jobs = 0
            worker.save(update_fields=['status', 'current_running_jobs'])
        except Exception:
            pass


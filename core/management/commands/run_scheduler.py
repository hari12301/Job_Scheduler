import time
import signal
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import ScheduledJob, Job, Worker, DeadLetterQueueEntry
from core.engine.cron_parser import get_next_cron_run
from core.engine.dag_engine import resolve_workflow_dependencies
from core.engine.ai_summarizer import generate_ai_failure_summary

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Runs the central Scheduler and Zombie Worker Reaper daemon."

    def add_arguments(self, parser):
        parser.add_argument('--tick-interval', type=float, default=2.0, help='Tick interval in seconds.')
        parser.add_argument('--once', action='store_true', help='Run single tick and exit.')

    def handle(self, *args, **options):
        tick_interval = options['tick_interval']
        run_once = options['once']

        self.stdout.write(self.style.SUCCESS("⏱️ Initializing Central Scheduler & Reaper Daemon..."))
        self.running = True

        def signal_handler(signum, frame):
            self.stdout.write(self.style.WARNING("\n🛑 Stopping Scheduler daemon..."))
            self.running = False

        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except Exception:
            pass

        try:
            while self.running:
                now = timezone.now()

                # 1. Process Recurring (Cron) Jobs
                self.process_cron_jobs(now)

                # 2. Activate Delayed / Scheduled Jobs
                self.activate_scheduled_jobs(now)

                # 3. Resolve DAG Workflow Dependencies
                unlocked, failed = resolve_workflow_dependencies()
                if unlocked > 0:
                    self.stdout.write(self.style.SUCCESS(f"🔗 DAG Engine: Unlocked {unlocked} workflow step(s)."))

                # 4. Reap Zombie Workers and recover stranded jobs
                self.reap_zombie_workers(now)

                if run_once:
                    break

                time.sleep(tick_interval)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Scheduler stopped by user."))

    def process_cron_jobs(self, now):
        cron_jobs = ScheduledJob.objects.filter(
            is_enabled=True
        ).filter(
            next_run_at__lte=now
        )

        for sched in cron_jobs:
            # Enqueue execution job instance
            Job.objects.create(
                project=sched.project,
                queue=sched.queue,
                name=f"{sched.name} [{now.strftime('%Y-%m-%d %H:%M')}]",
                job_type=Job.JobType.RECURRING,
                handler=sched.handler,
                status=Job.Status.QUEUED,
                payload=sched.payload,
                priority=sched.priority,
                scheduled_at=now
            )

            # Compute next run time
            sched.last_run_at = now
            sched.next_run_at = get_next_cron_run(sched.cron_expression, now)
            sched.save(update_fields=['last_run_at', 'next_run_at', 'updated_at'])

            self.stdout.write(self.style.NOTICE(
                f"📅 Enqueued Cron Job '{sched.name}'. Next run: {sched.next_run_at.isoformat()}"
            ))

    def activate_scheduled_jobs(self, now):
        activated_count = Job.objects.filter(
            status__in=[Job.Status.DELAYED, Job.Status.SCHEDULED],
            scheduled_at__lte=now
        ).update(status=Job.Status.QUEUED)

        if activated_count > 0:
            self.stdout.write(self.style.SUCCESS(f"⏰ Activated {activated_count} delayed/scheduled job(s) to QUEUED."))

    def reap_zombie_workers(self, now):
        threshold = now - timedelta(seconds=30)
        dead_workers = Worker.objects.filter(
            last_heartbeat_at__lt=threshold,
            status=Worker.Status.ACTIVE
        )

        for worker in dead_workers:
            self.stdout.write(self.style.ERROR(
                f"💀 Detected Zombie Worker '{worker.hostname}' (PID {worker.pid}). Marking DEAD..."
            ))
            worker.status = Worker.Status.DEAD
            worker.save(update_fields=['status'])

            # Recover orphaned claimed/running jobs
            stranded_jobs = Job.objects.filter(
                claimed_by_worker=worker,
                status__in=[Job.Status.CLAIMED, Job.Status.RUNNING]
            )

            for job in stranded_jobs:
                if job.current_attempt < job.max_retries:
                    self.stdout.write(self.style.WARNING(
                        f"♻️ Re-queueing orphaned job '{job.name}' (attempt {job.current_attempt}/{job.max_retries})"
                    ))
                    job.status = Job.Status.QUEUED
                    job.claimed_by_worker = None
                    job.claimed_at = None
                    job.save(update_fields=['status', 'claimed_by_worker', 'claimed_at'])
                else:
                    self.stdout.write(self.style.ERROR(
                        f"☠️ Job '{job.name}' exceeded retries due to worker crash. Moving to DLQ."
                    ))
                    job.status = Job.Status.DEAD_LETTER
                    job.completed_at = now
                    job.error_message = "Worker process terminated abruptly / missed heartbeats."
                    job.save(update_fields=['status', 'completed_at', 'error_message'])

                    cat, summary = generate_ai_failure_summary(job.name, job.error_message, "")
                    DeadLetterQueueEntry.objects.update_or_create(
                        job=job,
                        defaults={
                            'original_queue': job.queue,
                            'failure_reason': job.error_message,
                            'failure_category': cat,
                            'ai_summary': summary
                        }
                    )


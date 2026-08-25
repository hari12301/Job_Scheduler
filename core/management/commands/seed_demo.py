import uuid
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import (
    Organization, Project, APIKey, RetryPolicy,
    Queue, Worker, Job, JobDependency, JobExecution,
    JobLog, ScheduledJob, DeadLetterQueueEntry
)
from core.engine.cron_parser import get_next_cron_run
from core.engine.ai_summarizer import generate_ai_failure_summary

class Command(BaseCommand):
    help = "Seeds comprehensive sample data for distributed scheduler testing & dashboard visualization."

    def handle(self, *args, **options):
        self.stdout.write("🌱 Seeding realistic demo data...")

        # 1. Organizations
        org, _ = Organization.objects.get_or_create(
            slug='acme-cloud',
            defaults={'name': 'Acme Cloud Platform'}
        )

        # 2. Projects
        proj_payments, _ = Project.objects.get_or_create(
            organization=org,
            slug='payment-services',
            defaults={'name': 'Payment & Billing Services', 'description': 'Critical transaction processing pipeline.'}
        )

        proj_analytics, _ = Project.objects.get_or_create(
            organization=org,
            slug='analytics-engine',
            defaults={'name': 'Analytics & Data Platform', 'description': 'Real-time clickstream and warehouse ETL pipelines.'}
        )

        # 3. API Keys
        if not APIKey.objects.filter(project=proj_payments).exists():
            api_key, raw_token = APIKey.generate_key(proj_payments, 'Production Billing Key')
            self.stdout.write(self.style.SUCCESS(f"🔑 Created API Key for Payment Services: {raw_token}"))

        # 4. Retry Policies
        policy_exp, _ = RetryPolicy.objects.get_or_create(
            project=proj_payments,
            name='Exponential Standard',
            defaults={
                'strategy': RetryPolicy.Strategy.EXPONENTIAL_BACKOFF,
                'max_retries': 4,
                'initial_interval_seconds': 5,
                'max_interval_seconds': 300,
                'backoff_multiplier': 2.0,
                'jitter': True
            }
        )

        policy_linear, _ = RetryPolicy.objects.get_or_create(
            project=proj_analytics,
            name='Linear Fast',
            defaults={
                'strategy': RetryPolicy.Strategy.LINEAR_BACKOFF,
                'max_retries': 3,
                'initial_interval_seconds': 10,
                'max_interval_seconds': 60,
                'jitter': False
            }
        )

        # 5. Queues
        q_critical, _ = Queue.objects.get_or_create(
            project=proj_payments,
            name='critical-payments',
            defaults={'priority': 100, 'concurrency_limit': 20, 'rate_limit_per_second': 50, 'default_retry_policy': policy_exp}
        )

        q_etl, _ = Queue.objects.get_or_create(
            project=proj_analytics,
            name='analytics-etl',
            defaults={'priority': 50, 'concurrency_limit': 10, 'rate_limit_per_second': 20, 'default_retry_policy': policy_linear}
        )

        q_default, _ = Queue.objects.get_or_create(
            project=proj_payments,
            name='default',
            defaults={'priority': 20, 'concurrency_limit': 15}
        )

        q_notifications, _ = Queue.objects.get_or_create(
            project=proj_payments,
            name='notifications',
            defaults={'priority': 10, 'concurrency_limit': 30}
        )

        # 6. Workers
        w1, _ = Worker.objects.get_or_create(
            hostname='worker-node-alpha.internal',
            pid=1024,
            defaults={
                'status': Worker.Status.ACTIVE,
                'concurrency': 8,
                'current_running_jobs': 2,
                'cpu_usage_pct': 34.5,
                'memory_usage_mb': 512.0,
                'started_at': timezone.now() - timezone.timedelta(hours=6),
                'last_heartbeat_at': timezone.now()
            }
        )

        w2, _ = Worker.objects.get_or_create(
            hostname='worker-node-beta.internal',
            pid=2048,
            defaults={
                'status': Worker.Status.ACTIVE,
                'concurrency': 8,
                'current_running_jobs': 1,
                'cpu_usage_pct': 18.2,
                'memory_usage_mb': 420.0,
                'started_at': timezone.now() - timezone.timedelta(hours=12),
                'last_heartbeat_at': timezone.now()
            }
        )

        # 7. Completed Jobs with Logs & Execution
        for i in range(1, 6):
            job = Job.objects.create(
                project=proj_payments,
                queue=q_critical,
                name=f"Process Payment TXN-902{i}",
                job_type=Job.JobType.IMMEDIATE,
                handler='http_request',
                status=Job.Status.COMPLETED,
                payload={'url': 'https://api.stripe.com/v1/charges', 'amount': 4900, 'currency': 'USD'},
                result={'status_code': 200, 'transaction_id': f'ch_3M4{i}982'},
                priority=100,
                started_at=timezone.now() - timezone.timedelta(minutes=10 * i),
                completed_at=timezone.now() - timezone.timedelta(minutes=10 * i - 1),
                claimed_by_worker=w1,
                current_attempt=1
            )
            exec_rec = JobExecution.objects.create(
                job=job,
                worker=w1,
                attempt_number=1,
                status=JobExecution.ExecutionStatus.COMPLETED,
                started_at=job.started_at,
                finished_at=job.completed_at,
                duration_ms=450
            )
            JobLog.objects.create(job=job, execution=exec_rec, level='INFO', message=f"Transaction TXN-902{i} authorized successfully.")

        # 8. Queued Immediate Jobs
        for i in range(1, 4):
            Job.objects.create(
                project=proj_payments,
                queue=q_critical,
                name=f"Authorize Card Auth-{i}00",
                job_type=Job.JobType.IMMEDIATE,
                handler='mock_task',
                status=Job.Status.QUEUED,
                payload={'card_last4': '4242', 'amount_cents': 9900},
                priority=100
            )

        # 9. Delayed Job
        Job.objects.create(
            project=proj_payments,
            queue=q_default,
            name="Send Subscription Expiry Reminder",
            job_type=Job.JobType.DELAYED,
            handler='email_dispatch',
            status=Job.Status.DELAYED,
            payload={'to': 'customer@example.com', 'subject': 'Subscription Renewal Reminder'},
            scheduled_at=timezone.now() + timezone.timedelta(minutes=15)
        )

        # 10. DLQ Failed Job with AI Diagnosis
        failed_job = Job.objects.create(
            project=proj_analytics,
            queue=q_etl,
            name="Sync Postgres to Clickhouse Warehouse",
            job_type=Job.JobType.IMMEDIATE,
            handler='data_pipeline',
            status=Job.Status.DEAD_LETTER,
            payload={'dataset': 'user_clickstream', 'batch_size': 50000},
            error_message="ReadTimeout: Upstream socket read timed out after 30000ms",
            error_stack="Traceback (most recent call last):\n  File \"core/engine/executor.py\", line 124, in execute_job\n    raise TimeoutError('Upstream socket read timeout after 30000ms')",
            current_attempt=3,
            max_retries=3,
            completed_at=timezone.now() - timezone.timedelta(minutes=30)
        )
        cat, ai_sum = generate_ai_failure_summary(failed_job.name, failed_job.error_message, failed_job.error_stack)
        DeadLetterQueueEntry.objects.create(
            job=failed_job,
            original_queue=q_etl,
            failure_reason=failed_job.error_message,
            failure_category=cat,
            ai_summary=ai_sum
        )

        # 11. Recurring Cron Jobs
        ScheduledJob.objects.get_or_create(
            project=proj_analytics,
            queue=q_etl,
            name="Daily Revenue Aggregation",
            defaults={
                'handler': 'data_pipeline',
                'cron_expression': '0 0 * * *',
                'payload': {'dataset': 'daily_revenue_mart'},
                'priority': 50,
                'is_enabled': True,
                'next_run_at': get_next_cron_run('0 0 * * *')
            }
        )

        ScheduledJob.objects.get_or_create(
            project=proj_payments,
            queue=q_critical,
            name="Heartbeat Health Ping",
            defaults={
                'handler': 'mock_task',
                'cron_expression': '*/5 * * * *',
                'payload': {'service': 'billing_api'},
                'priority': 80,
                'is_enabled': True,
                'next_run_at': get_next_cron_run('*/5 * * * *')
            }
        )

        # 12. Multi-step DAG Workflow (ETL Pipeline)
        batch_id = uuid.uuid4()
        step1 = Job.objects.create(
            project=proj_analytics,
            queue=q_etl,
            name="ETL Pipeline: 1. Extract Raw S3 Logs",
            job_type=Job.JobType.WORKFLOW_STEP,
            handler='data_pipeline',
            status=Job.Status.COMPLETED,
            payload={'s3_bucket': 'app-logs-2026'},
            batch_id=batch_id,
            completed_at=timezone.now() - timezone.timedelta(minutes=5)
        )

        step2 = Job.objects.create(
            project=proj_analytics,
            queue=q_etl,
            name="ETL Pipeline: 2. Validate Data Schema",
            job_type=Job.JobType.WORKFLOW_STEP,
            handler='mock_task',
            status=Job.Status.COMPLETED,
            payload={'validator': 'pydantic_v2'},
            batch_id=batch_id,
            completed_at=timezone.now() - timezone.timedelta(minutes=4)
        )
        JobDependency.objects.create(job=step2, depends_on=step1)

        step3 = Job.objects.create(
            project=proj_analytics,
            queue=q_etl,
            name="ETL Pipeline: 3. Transform & Deduplicate",
            job_type=Job.JobType.WORKFLOW_STEP,
            handler='mock_task',
            status=Job.Status.QUEUED,
            payload={'dedup_strategy': 'bloom_filter'},
            batch_id=batch_id
        )
        JobDependency.objects.create(job=step3, depends_on=step2)

        step4 = Job.objects.create(
            project=proj_analytics,
            queue=q_etl,
            name="ETL Pipeline: 4. Load Warehouse Table",
            job_type=Job.JobType.WORKFLOW_STEP,
            handler='data_pipeline',
            status=Job.Status.PENDING,
            payload={'target_table': 'fact_analytics'},
            batch_id=batch_id
        )
        JobDependency.objects.create(job=step4, depends_on=step3)

        step5 = Job.objects.create(
            project=proj_payments,
            queue=q_notifications,
            name="ETL Pipeline: 5. Send Slack Notification",
            job_type=Job.JobType.WORKFLOW_STEP,
            handler='email_dispatch',
            status=Job.Status.PENDING,
            payload={'channel': '#data-alerts', 'message': 'Daily ETL Completed'},
            batch_id=batch_id
        )
        JobDependency.objects.create(job=step5, depends_on=step4)

        self.stdout.write(self.style.SUCCESS("✨ Successfully seeded comprehensive demo data and DAG workflow!"))


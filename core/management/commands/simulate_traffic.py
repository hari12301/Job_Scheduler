import time
import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Project, Queue, Job

class Command(BaseCommand):
    help = "Simulates incoming job traffic continuously for dashboard demonstration."

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=float, default=1.5, help='Seconds between new jobs.')
        parser.add_argument('--count', type=int, default=0, help='Total jobs to generate (0 = infinite).')

    def handle(self, *args, **options):
        interval = options['interval']
        max_count = options['count']

        queues = list(Queue.objects.filter(is_paused=False))
        if not queues:
            self.stdout.write(self.style.ERROR("No active queues found. Run 'python manage.py seed_demo' first."))
            return

        self.stdout.write(self.style.SUCCESS(f"⚡ Starting traffic simulation (Interval: {interval}s)..."))

        task_types = [
            ('Process Stripe Payment', 'http_request', {'url': 'https://api.stripe.com/v1/charges', 'amount': 2500}),
            ('Send Welcome Email', 'email_dispatch', {'to': 'user@example.com', 'subject': 'Welcome!'}),
            ('Clickstream Ingestion', 'data_pipeline', {'dataset': 'clicks_raw', 'batch_size': 100}),
            ('Compute Fraud Score', 'mock_task', {'duration_seconds': 0.8, 'fail_rate': 0.05}),
            ('Generate Monthly Invoice', 'mock_task', {'duration_seconds': 1.2, 'fail_rate': 0.1}),
            ('Webhook Notification', 'http_request', {'url': 'https://webhook.site/test', 'method': 'POST'}),
        ]

        generated = 0
        try:
            while True:
                queue = random.choice(queues)
                title, handler, payload = random.choice(task_types)
                
                # Random priority variance
                priority = random.choice([queue.priority, queue.priority + 5, max(1, queue.priority - 5)])
                
                job = Job.objects.create(
                    project=queue.project,
                    queue=queue,
                    name=f"{title} #{random.randint(1000, 9999)}",
                    job_type=Job.JobType.IMMEDIATE,
                    handler=handler,
                    status=Job.Status.QUEUED,
                    payload=payload,
                    priority=priority,
                    scheduled_at=timezone.now()
                )

                generated += 1
                self.stdout.write(self.style.NOTICE(
                    f"[{generated}] Enqueued '{job.name}' -> Queue [{queue.name}] (Priority: {priority})"
                ))

                if max_count > 0 and generated >= max_count:
                    break

                time.sleep(interval)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING(f"Traffic simulation stopped. Generated {generated} jobs."))


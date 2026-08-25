from django.test import TestCase
from django.utils import timezone
from core.models import Organization, Project, Queue, Job, RetryPolicy
from core.engine.retry import calculate_next_retry

class RetryPolicyTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(organization=self.org, name="Platform", slug="platform")
        self.queue = Queue.objects.create(project=self.project, name="default")

    def test_fixed_retry(self):
        policy = RetryPolicy.objects.create(
            project=self.project,
            name="Fixed 10s",
            strategy=RetryPolicy.Strategy.FIXED,
            initial_interval_seconds=10,
            jitter=False
        )
        job = Job.objects.create(project=self.project, queue=self.queue, name="Job", retry_policy=policy, current_attempt=1)
        next_dt = calculate_next_retry(job)
        delta_sec = (next_dt - timezone.now()).total_seconds()
        self.assertAlmostEqual(delta_sec, 10, delta=2)

    def test_linear_retry(self):
        policy = RetryPolicy.objects.create(
            project=self.project,
            name="Linear 5s",
            strategy=RetryPolicy.Strategy.LINEAR_BACKOFF,
            initial_interval_seconds=5,
            jitter=False
        )
        job = Job.objects.create(project=self.project, queue=self.queue, name="Job", retry_policy=policy, current_attempt=3)
        next_dt = calculate_next_retry(job)
        delta_sec = (next_dt - timezone.now()).total_seconds()
        self.assertAlmostEqual(delta_sec, 15, delta=2)

    def test_exponential_retry(self):
        policy = RetryPolicy.objects.create(
            project=self.project,
            name="Exp 2s",
            strategy=RetryPolicy.Strategy.EXPONENTIAL_BACKOFF,
            initial_interval_seconds=2,
            backoff_multiplier=2.0,
            jitter=False
        )
        # Attempt 3: delay = 2 * (2 ** (3-1)) = 8s
        job = Job.objects.create(project=self.project, queue=self.queue, name="Job", retry_policy=policy, current_attempt=3)
        next_dt = calculate_next_retry(job)
        delta_sec = (next_dt - timezone.now()).total_seconds()
        self.assertAlmostEqual(delta_sec, 8, delta=2)


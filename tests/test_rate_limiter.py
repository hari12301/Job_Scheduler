from django.test import TestCase
from core.models import Organization, Project, Queue
from core.engine.rate_limiter import check_and_consume_rate_limit

class RateLimiterTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(organization=self.org, name="Platform", slug="platform")
        self.queue = Queue.objects.create(
            project=self.project,
            name="limited-queue",
            rate_limit_per_second=2,
            burst_limit=2
        )

    def test_token_consumption(self):
        # 1st token
        self.assertTrue(check_and_consume_rate_limit(self.queue, 1.0))
        # 2nd token
        self.assertTrue(check_and_consume_rate_limit(self.queue, 1.0))
        # 3rd token (exhausted burst)
        self.assertFalse(check_and_consume_rate_limit(self.queue, 1.0))


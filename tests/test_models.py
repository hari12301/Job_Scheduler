from django.test import TestCase
from django.utils import timezone
from core.models import Organization, Project, Queue, Job, Worker, RetryPolicy, DeadLetterQueueEntry

class ModelTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme Corp", slug="acme")
        self.project = Project.objects.create(organization=self.org, name="Backend", slug="backend")
        self.queue = Queue.objects.create(project=self.project, name="high-priority", priority=100)

    def test_organization_and_project_creation(self):
        self.assertEqual(str(self.org), "Acme Corp")
        self.assertEqual(str(self.project), "Acme Corp / Backend")

    def test_queue_creation(self):
        self.assertEqual(self.queue.priority, 100)
        self.assertEqual(self.queue.concurrency_limit, 10)
        self.assertFalse(self.queue.is_paused)

    def test_job_creation(self):
        job = Job.objects.create(
            project=self.project,
            queue=self.queue,
            name="Send Notification",
            handler="email_dispatch",
            payload={"to": "dev@acme.com"}
        )
        self.assertEqual(job.status, Job.Status.QUEUED)
        self.assertEqual(job.current_attempt, 0)
        self.assertEqual(job.max_retries, 3)

    def test_worker_registration(self):
        worker = Worker.objects.create(
            hostname="worker-node-1",
            pid=1234,
            concurrency=4
        )
        self.assertTrue(worker.is_alive)
        self.assertEqual(worker.status, Worker.Status.ACTIVE)


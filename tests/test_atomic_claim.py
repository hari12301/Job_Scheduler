from django.test import TestCase
from django.utils import timezone
from core.models import Organization, Project, Queue, Job, Worker
from core.engine.claimer import claim_jobs_for_worker

class AtomicClaimTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(organization=self.org, name="Platform", slug="platform")
        
        self.queue_high = Queue.objects.create(project=self.project, name="high", priority=100, concurrency_limit=5)
        self.queue_low = Queue.objects.create(project=self.project, name="low", priority=10, concurrency_limit=5)

        self.worker = Worker.objects.create(hostname="worker-test", pid=999, concurrency=4)

    def test_priority_claiming(self):
        # Create low priority job
        j_low = Job.objects.create(project=self.project, queue=self.queue_low, name="Low Job", priority=10)
        # Create high priority job
        j_high = Job.objects.create(project=self.project, queue=self.queue_high, name="High Job", priority=100)

        claimed = claim_jobs_for_worker(self.worker, limit=1)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].id, j_high.id)
        self.assertEqual(claimed[0].status, Job.Status.CLAIMED)
        self.assertEqual(claimed[0].claimed_by_worker, self.worker)

    def test_queue_pause_prevents_claim(self):
        self.queue_high.is_paused = True
        self.queue_high.save()

        Job.objects.create(project=self.project, queue=self.queue_high, name="Job on paused queue")
        claimed = claim_jobs_for_worker(self.worker, limit=5)
        self.assertEqual(len(claimed), 0)

    def test_queue_concurrency_limit_enforced(self):
        self.queue_high.concurrency_limit = 1
        self.queue_high.save()

        # Job 1 already running
        Job.objects.create(project=self.project, queue=self.queue_high, name="Running Job", status=Job.Status.RUNNING)
        # Job 2 queued
        Job.objects.create(project=self.project, queue=self.queue_high, name="Queued Job", status=Job.Status.QUEUED)

        claimed = claim_jobs_for_worker(self.worker, limit=1)
        self.assertEqual(len(claimed), 0)  # Cannot claim because limit of 1 is reached


from django.test import TestCase
from core.models import Organization, Project, Queue, Job, JobDependency
from core.engine.dag_engine import resolve_workflow_dependencies

class DAGWorkflowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(organization=self.org, name="Platform", slug="platform")
        self.queue = Queue.objects.create(project=self.project, name="default")

    def test_dag_resolution_unlocks_child(self):
        # Step 1: Parent Job
        parent = Job.objects.create(
            project=self.project,
            queue=self.queue,
            name="Step 1: Extract",
            status=Job.Status.RUNNING
        )

        # Step 2: Child Job
        child = Job.objects.create(
            project=self.project,
            queue=self.queue,
            name="Step 2: Transform",
            status=Job.Status.PENDING
        )
        JobDependency.objects.create(job=child, depends_on=parent)

        # Resolve while parent is still running
        unlocked, failed = resolve_workflow_dependencies()
        self.assertEqual(unlocked, 0)
        child.refresh_from_db()
        self.assertEqual(child.status, Job.Status.PENDING)

        # Complete parent
        parent.status = Job.Status.COMPLETED
        parent.save()

        # Resolve again
        unlocked, failed = resolve_workflow_dependencies()
        self.assertEqual(unlocked, 1)
        child.refresh_from_db()
        self.assertEqual(child.status, Job.Status.QUEUED)

    def test_dag_parent_failure_fails_child(self):
        parent = Job.objects.create(
            project=self.project,
            queue=self.queue,
            name="Parent Step",
            status=Job.Status.FAILED
        )
        child = Job.objects.create(
            project=self.project,
            queue=self.queue,
            name="Child Step",
            status=Job.Status.PENDING
        )
        JobDependency.objects.create(job=child, depends_on=parent)

        unlocked, failed = resolve_workflow_dependencies()
        self.assertEqual(failed, 1)
        child.refresh_from_db()
        self.assertEqual(child.status, Job.Status.FAILED)
        self.assertIn("Upstream dependency failed", child.error_message)


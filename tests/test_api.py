from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from core.models import Organization, Project, Queue, Job

class APITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.project = Project.objects.create(organization=self.org, name="Platform", slug="platform")
        self.queue = Queue.objects.create(project=self.project, name="default", priority=50)

    def test_list_queues(self):
        response = self.client.get('/api/v1/queues/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_create_and_retry_job(self):
        # Create Job
        payload = {
            'project': str(self.project.id),
            'queue': str(self.queue.id),
            'name': 'API Test Job',
            'handler': 'mock_task',
            'payload': {'key': 'val'}
        }
        res = self.client.post('/api/v1/jobs/', payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        job_id = res.data['id']

        # Fail and Retry
        job = Job.objects.get(id=job_id)
        job.status = Job.Status.FAILED
        job.save()

        retry_res = self.client.post(f'/api/v1/jobs/{job_id}/retry/')
        self.assertEqual(retry_res.status_code, status.HTTP_200_OK)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.QUEUED)

    def test_queue_pause_resume(self):
        res = self.client.post(f'/api/v1/queues/{self.queue.id}/pause/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.queue.refresh_from_db()
        self.assertTrue(self.queue.is_paused)

        res = self.client.post(f'/api/v1/queues/{self.queue.id}/resume/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.queue.refresh_from_db()
        self.assertFalse(self.queue.is_paused)


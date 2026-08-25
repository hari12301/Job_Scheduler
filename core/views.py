import uuid
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from django.db.models import Count, Avg, Max, Min, Q
from django.shortcuts import get_object_or_404

from core.models import (
    Organization, Project, APIKey, RetryPolicy,
    Queue, Worker, WorkerHeartbeat, Job, JobDependency,
    JobExecution, JobLog, ScheduledJob, DeadLetterQueueEntry
)
from core.serializers import (
    OrganizationSerializer, ProjectSerializer, APIKeySerializer,
    RetryPolicySerializer, QueueSerializer, WorkerSerializer,
    JobSerializer, CreateJobSerializer, BatchJobCreateSerializer,
    WorkflowCreateSerializer, JobExecutionSerializer, JobLogSerializer,
    ScheduledJobSerializer, DeadLetterQueueEntrySerializer
)
from core.permissions import HasProjectPermission
from core.engine.cron_parser import get_next_cron_run

class OrganizationViewSet(viewsets.ModelViewSet):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    permission_classes = [HasProjectPermission]


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [HasProjectPermission]

    @action(detail=True, methods=['post'])
    def generate_api_key(self, request, pk=None):
        project = self.get_object()
        name = request.data.get('name', 'Default Key')
        api_key, raw_token = APIKey.generate_key(project, name)
        return Response({
            'id': str(api_key.id),
            'name': api_key.name,
            'api_key': raw_token,
            'key_prefix': api_key.key_prefix,
            'message': 'Save this key now. It will not be shown again.'
        }, status=status.HTTP_201_CREATED)


class RetryPolicyViewSet(viewsets.ModelViewSet):
    queryset = RetryPolicy.objects.all()
    serializer_class = RetryPolicySerializer
    permission_classes = [HasProjectPermission]


class QueueViewSet(viewsets.ModelViewSet):
    queryset = Queue.objects.all()
    serializer_class = QueueSerializer
    permission_classes = [HasProjectPermission]

    def get_queryset(self):
        qs = Queue.objects.all()
        project_id = self.request.query_params.get('project_id')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        queue = self.get_object()
        queue.is_paused = True
        queue.save(update_fields=['is_paused', 'updated_at'])
        return Response({'status': 'paused', 'queue': queue.name})

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        queue = self.get_object()
        queue.is_paused = False
        queue.save(update_fields=['is_paused', 'updated_at'])
        return Response({'status': 'active', 'queue': queue.name})

    @action(detail=True, methods=['post'])
    def purge(self, request, pk=None):
        queue = self.get_object()
        deleted_count, _ = queue.jobs.filter(status__in=[Job.Status.QUEUED, Job.Status.PENDING]).delete()
        return Response({'status': 'purged', 'jobs_removed': deleted_count})

    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        queue = self.get_object()
        counts = queue.jobs.values('status').annotate(count=Count('status'))
        stat_dict = {c['status']: c['count'] for c in counts}
        return Response({
            'queue_id': str(queue.id),
            'queue_name': queue.name,
            'is_paused': queue.is_paused,
            'concurrency_limit': queue.concurrency_limit,
            'rate_limit_per_second': queue.rate_limit_per_second,
            'status_distribution': stat_dict
        })


class JobViewSet(viewsets.ModelViewSet):
    queryset = Job.objects.all().select_related('queue', 'project', 'claimed_by_worker').prefetch_related('dependencies__depends_on')
    permission_classes = [HasProjectPermission]

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateJobSerializer
        return JobSerializer

    def get_queryset(self):
        qs = Job.objects.all().select_related('queue', 'project', 'claimed_by_worker').prefetch_related('dependencies__depends_on')
        
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        queue_param = self.request.query_params.get('queue_id')
        if queue_param:
            qs = qs.filter(queue_id=queue_param)

        project_param = self.request.query_params.get('project_id')
        if project_param:
            qs = qs.filter(project_id=project_param)

        batch_param = self.request.query_params.get('batch_id')
        if batch_param:
            qs = qs.filter(batch_id=batch_param)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(idempotency_key__icontains=search) | Q(id__icontains=search))

        return qs.order_by('-created_at')

    @action(detail=False, methods=['post'], url_path='batch')
    def create_batch(self, request):
        serializer = BatchJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        job = self.get_object()
        job.status = Job.Status.QUEUED
        job.scheduled_at = timezone.now()
        job.claimed_by_worker = None
        job.claimed_at = None
        job.error_message = None
        job.error_stack = None
        job.save(update_fields=['status', 'scheduled_at', 'claimed_by_worker', 'claimed_at', 'error_message', 'error_stack'])

        # Remove from DLQ if present
        DeadLetterQueueEntry.objects.filter(job=job).delete()

        return Response({'status': 'requeued', 'job_id': str(job.id)})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        job = self.get_object()
        if job.status in [Job.Status.COMPLETED, Job.Status.CANCELLED]:
            return Response({'error': f'Cannot cancel job in {job.status} status'}, status=status.HTTP_400_BAD_REQUEST)
        job.status = Job.Status.CANCELLED
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])
        return Response({'status': 'cancelled', 'job_id': str(job.id)})

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        job = self.get_object()
        logs = job.logs.all().order_by('timestamp', 'id')
        serializer = JobLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def executions(self, request, pk=None):
        job = self.get_object()
        executions = job.executions.all().order_by('attempt_number')
        serializer = JobExecutionSerializer(executions, many=True)
        return Response(serializer.data)


class WorkflowViewSet(viewsets.ViewSet):
    permission_classes = [HasProjectPermission]

    def create(self, request):
        serializer = WorkflowCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='batch/(?P<batch_id>[^/.]+)')
    def get_workflow_graph(self, request, batch_id=None):
        jobs = Job.objects.filter(batch_id=batch_id).prefetch_related('dependencies__depends_on')
        if not jobs.exists():
            return Response({'error': 'Workflow not found'}, status=status.HTTP_404_NOT_FOUND)

        nodes = []
        links = []
        for j in jobs:
            nodes.append({
                'id': str(j.id),
                'name': j.name,
                'status': j.status,
                'duration_ms': j.duration_ms,
                'handler': j.handler
            })
            for dep in j.dependencies.all():
                links.append({
                    'source': str(dep.depends_on.id),
                    'target': str(j.id),
                    'required_status': dep.required_status
                })

        return Response({
            'batch_id': batch_id,
            'nodes': nodes,
            'links': links
        })


class ScheduledJobViewSet(viewsets.ModelViewSet):
    queryset = ScheduledJob.objects.all().select_related('queue', 'project')
    serializer_class = ScheduledJobSerializer
    permission_classes = [HasProjectPermission]

    @action(detail=True, methods=['post'])
    def trigger_now(self, request, pk=None):
        sched_job = self.get_object()
        job = Job.objects.create(
            project=sched_job.project,
            queue=sched_job.queue,
            name=f"{sched_job.name} (Manual Trigger)",
            job_type=Job.JobType.SCHEDULED,
            handler=sched_job.handler,
            status=Job.Status.QUEUED,
            payload=sched_job.payload,
            priority=sched_job.priority
        )
        return Response({'status': 'triggered', 'job_id': str(job.id)})

    @action(detail=True, methods=['post'])
    def toggle_enable(self, request, pk=None):
        sched_job = self.get_object()
        sched_job.is_enabled = not sched_job.is_enabled
        sched_job.save(update_fields=['is_enabled', 'updated_at'])
        return Response({'is_enabled': sched_job.is_enabled})


class WorkerViewSet(viewsets.ModelViewSet):
    queryset = Worker.objects.all()
    serializer_class = WorkerSerializer
    permission_classes = [HasProjectPermission]

    @action(detail=True, methods=['post'])
    def heartbeat(self, request, pk=None):
        worker = self.get_object()
        now = timezone.now()
        worker.last_heartbeat_at = now
        worker.status = request.data.get('status', Worker.Status.ACTIVE)
        worker.current_running_jobs = request.data.get('running_jobs', 0)
        worker.cpu_usage_pct = request.data.get('cpu_usage_pct', 0.0)
        worker.memory_usage_mb = request.data.get('memory_usage_mb', 0.0)
        worker.save(update_fields=['last_heartbeat_at', 'status', 'current_running_jobs', 'cpu_usage_pct', 'memory_usage_mb'])

        # Append heartbeat record
        WorkerHeartbeat.objects.create(
            worker=worker,
            running_job_count=worker.current_running_jobs,
            cpu_usage_pct=worker.cpu_usage_pct,
            memory_usage_mb=worker.memory_usage_mb
        )
        return Response({'status': 'heartbeat_received', 'timestamp': now.isoformat()})

    @action(detail=True, methods=['post'])
    def deregister(self, request, pk=None):
        worker = self.get_object()
        worker.status = Worker.Status.DEAD
        worker.save(update_fields=['status'])
        return Response({'status': 'deregistered'})


class DeadLetterQueueViewSet(viewsets.ModelViewSet):
    queryset = DeadLetterQueueEntry.objects.all().select_related('job', 'original_queue')
    serializer_class = DeadLetterQueueEntrySerializer
    permission_classes = [HasProjectPermission]

    @action(detail=True, methods=['post'])
    def replay(self, request, pk=None):
        entry = self.get_object()
        job = entry.job
        job.status = Job.Status.QUEUED
        job.scheduled_at = timezone.now()
        job.current_attempt = 0
        job.claimed_by_worker = None
        job.claimed_at = None
        job.error_message = None
        job.error_stack = None
        job.save()

        entry.replayed_at = timezone.now()
        entry.replay_count += 1
        entry.save(update_fields=['replayed_at', 'replay_count'])
        entry.delete()

        return Response({'status': 'replayed', 'job_id': str(job.id)})

    @action(detail=False, methods=['post'])
    def replay_all(self, request):
        entries = DeadLetterQueueEntry.objects.all()
        replayed_count = 0
        for entry in entries:
            job = entry.job
            job.status = Job.Status.QUEUED
            job.scheduled_at = timezone.now()
            job.current_attempt = 0
            job.claimed_by_worker = None
            job.claimed_at = None
            job.error_message = None
            job.error_stack = None
            job.save()
            replayed_count += 1
            entry.delete()

        return Response({'status': 'replayed_all', 'replayed_count': replayed_count})


class SystemMetricsView(APIView):
    """
    Returns aggregated real-time system metrics, throughput, latency percentiles, and queue depths.
    """
    permission_classes = [HasProjectPermission]

    def get(self, request):
        now = timezone.now()
        threshold_30s = now - timezone.timedelta(seconds=30)
        threshold_1h = now - timezone.timedelta(hours=1)

        # Worker metrics
        active_workers = Worker.objects.filter(last_heartbeat_at__gte=threshold_30s, status=Worker.Status.ACTIVE).count()
        total_workers = Worker.objects.count()

        # Job distribution
        status_counts = Job.objects.values('status').annotate(count=Count('status'))
        status_map = {item['status']: item['count'] for item in status_counts}

        # Execution stats (last 1 hour)
        recent_execs = JobExecution.objects.filter(started_at__gte=threshold_1h)
        total_processed_hour = recent_execs.count()
        failed_hour = recent_execs.filter(status=JobExecution.ExecutionStatus.FAILED).count()
        avg_latency_ms = recent_execs.filter(duration_ms__isnull=False).aggregate(avg=Avg('duration_ms'))['avg'] or 0

        # Queue summaries
        queues = Queue.objects.all()
        queue_stats = []
        for q in queues:
            queue_stats.append({
                'id': str(q.id),
                'name': q.name,
                'priority': q.priority,
                'is_paused': q.is_paused,
                'concurrency_limit': q.concurrency_limit,
                'queued_count': q.jobs.filter(status=Job.Status.QUEUED).count(),
                'running_count': q.jobs.filter(status=Job.Status.RUNNING).count(),
                'completed_count': q.jobs.filter(status=Job.Status.COMPLETED).count(),
                'failed_count': q.jobs.filter(status__in=[Job.Status.FAILED, Job.Status.DEAD_LETTER]).count(),
            })

        dlq_count = DeadLetterQueueEntry.objects.count()

        return Response({
            'timestamp': now.isoformat(),
            'active_workers': active_workers,
            'total_workers': total_workers,
            'total_jobs': Job.objects.count(),
            'dlq_count': dlq_count,
            'status_distribution': status_map,
            'hourly_stats': {
                'processed': total_processed_hour,
                'failed': failed_hour,
                'avg_latency_ms': round(avg_latency_ms, 2),
                'success_rate_pct': round(((total_processed_hour - failed_hour) / total_processed_hour * 100), 1) if total_processed_hour > 0 else 100.0
            },
            'queues': queue_stats
        })


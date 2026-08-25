import uuid
from rest_framework import serializers
from django.utils import timezone
from django.db import transaction
from core.models import (
    Organization, Project, ProjectMembership, APIKey,
    RetryPolicy, Queue, Worker, WorkerHeartbeat,
    Job, JobDependency, JobExecution, JobLog,
    ScheduledJob, DeadLetterQueueEntry
)
from core.engine.cron_parser import get_next_cron_run

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'created_at', 'updated_at']


class ProjectSerializer(serializers.ModelSerializer):
    organization_name = serializers.ReadOnlyField(source='organization.name')

    class Meta:
        model = Project
        fields = ['id', 'organization', 'organization_name', 'name', 'slug', 'description', 'is_active', 'created_at']


class APIKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = APIKey
        fields = ['id', 'project', 'name', 'key_prefix', 'is_active', 'last_used_at', 'created_at']
        read_only_fields = ['key_prefix', 'last_used_at', 'created_at']


class RetryPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = RetryPolicy
        fields = [
            'id', 'project', 'name', 'strategy', 'max_retries',
            'initial_interval_seconds', 'max_interval_seconds',
            'backoff_multiplier', 'jitter', 'created_at'
        ]


class QueueSerializer(serializers.ModelSerializer):
    active_jobs_count = serializers.ReadOnlyField()
    queued_jobs_count = serializers.ReadOnlyField()
    project_name = serializers.ReadOnlyField(source='project.name')

    class Meta:
        model = Queue
        fields = [
            'id', 'project', 'project_name', 'name', 'priority',
            'concurrency_limit', 'rate_limit_per_second', 'burst_limit',
            'is_paused', 'default_retry_policy',
            'active_jobs_count', 'queued_jobs_count', 'created_at'
        ]


class WorkerSerializer(serializers.ModelSerializer):
    is_alive = serializers.ReadOnlyField()

    class Meta:
        model = Worker
        fields = [
            'id', 'hostname', 'pid', 'status', 'concurrency',
            'current_running_jobs', 'total_processed_jobs', 'total_failed_jobs',
            'cpu_usage_pct', 'memory_usage_mb', 'queues_subscribed',
            'started_at', 'last_heartbeat_at', 'is_alive'
        ]


class JobExecutionSerializer(serializers.ModelSerializer):
    worker_name = serializers.ReadOnlyField(source='worker.hostname')

    class Meta:
        model = JobExecution
        fields = [
            'id', 'job', 'worker', 'worker_name', 'attempt_number',
            'status', 'started_at', 'finished_at', 'duration_ms',
            'exit_code', 'error_message', 'error_stack'
        ]


class JobLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobLog
        fields = ['id', 'job', 'execution', 'timestamp', 'level', 'message', 'metadata']


class JobDependencySerializer(serializers.ModelSerializer):
    depends_on_name = serializers.ReadOnlyField(source='depends_on.name')
    depends_on_status = serializers.ReadOnlyField(source='depends_on.status')

    class Meta:
        model = JobDependency
        fields = ['id', 'job', 'depends_on', 'depends_on_name', 'depends_on_status', 'required_status', 'created_at']


class JobSerializer(serializers.ModelSerializer):
    queue_name = serializers.ReadOnlyField(source='queue.name')
    project_name = serializers.ReadOnlyField(source='project.name')
    duration_ms = serializers.ReadOnlyField()
    dependencies = JobDependencySerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = [
            'id', 'project', 'project_name', 'queue', 'queue_name',
            'name', 'job_type', 'handler', 'status', 'priority',
            'payload', 'result', 'error_message', 'error_stack',
            'idempotency_key', 'scheduled_at', 'timeout_seconds',
            'max_retries', 'current_attempt', 'retry_policy',
            'claimed_by_worker', 'claimed_at', 'started_at', 'completed_at',
            'batch_id', 'parent_job', 'duration_ms', 'dependencies', 'created_at'
        ]
        read_only_fields = ['status', 'result', 'error_message', 'error_stack', 'current_attempt', 'claimed_by_worker', 'claimed_at', 'started_at', 'completed_at']


class CreateJobSerializer(serializers.ModelSerializer):
    """Handles creation of Immediate, Delayed, Scheduled jobs with idempotency."""
    delay_seconds = serializers.IntegerField(required=False, default=0, write_only=True)
    depends_on_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True, default=list
    )

    class Meta:
        model = Job
        fields = [
            'id', 'project', 'queue', 'name', 'job_type', 'handler',
            'priority', 'payload', 'idempotency_key', 'scheduled_at',
            'timeout_seconds', 'max_retries', 'retry_policy',
            'delay_seconds', 'depends_on_ids'
        ]

    def create(self, validated_data):
        delay_seconds = validated_data.pop('delay_seconds', 0)
        depends_on_ids = validated_data.pop('depends_on_ids', [])
        idempotency_key = validated_data.get('idempotency_key')
        project = validated_data.get('project')

        # Idempotency check
        if idempotency_key:
            existing = Job.objects.filter(project=project, idempotency_key=idempotency_key).first()
            if existing:
                return existing

        # Delayed scheduling
        if delay_seconds > 0:
            validated_data['scheduled_at'] = timezone.now() + timezone.timedelta(seconds=delay_seconds)
            validated_data['job_type'] = Job.JobType.DELAYED

        # If has dependencies, start in PENDING status
        if depends_on_ids:
            validated_data['status'] = Job.Status.PENDING
            validated_data['job_type'] = Job.JobType.WORKFLOW_STEP
        else:
            validated_data['status'] = Job.Status.QUEUED

        job = super().create(validated_data)

        # Create dependencies
        for dep_id in depends_on_ids:
            JobDependency.objects.create(job=job, depends_on_id=dep_id)

        return job


class BatchJobCreateSerializer(serializers.Serializer):
    """Creates a batch of jobs in a single request with a shared batch_id."""
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    queue = serializers.PrimaryKeyRelatedField(queryset=Queue.objects.all())
    batch_name = serializers.CharField(max_length=255)
    handler = serializers.CharField(max_length=255, default='mock_task')
    items = serializers.ListField(child=serializers.DictField(), min_length=1)

    def create(self, validated_data):
        project = validated_data['project']
        queue = validated_data['queue']
        batch_name = validated_data['batch_name']
        handler = validated_data['handler']
        items = validated_data['items']

        batch_id = uuid.uuid4()
        created_jobs = []

        with transaction.atomic():
            for idx, item in enumerate(items):
                job = Job.objects.create(
                    project=project,
                    queue=queue,
                    name=f"{batch_name} [Item #{idx + 1}]",
                    job_type=Job.JobType.BATCH_CHILD,
                    handler=handler,
                    status=Job.Status.QUEUED,
                    payload=item,
                    batch_id=batch_id,
                    priority=queue.priority
                )
                created_jobs.append(job)

        return {
            'batch_id': batch_id,
            'total_jobs_created': len(created_jobs),
            'jobs': [str(j.id) for j in created_jobs]
        }


class WorkflowStepSerializer(serializers.Serializer):
    step_id = serializers.CharField(max_length=100)
    name = serializers.CharField(max_length=255)
    handler = serializers.CharField(max_length=255, default='mock_task')
    payload = serializers.DictField(default=dict)
    depends_on = serializers.ListField(child=serializers.CharField(), default=list)


class WorkflowCreateSerializer(serializers.Serializer):
    """Creates a full multi-step DAG workflow atomically."""
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    queue = serializers.PrimaryKeyRelatedField(queryset=Queue.objects.all())
    workflow_name = serializers.CharField(max_length=255)
    steps = WorkflowStepSerializer(many=True, min_length=1)

    def create(self, validated_data):
        project = validated_data['project']
        queue = validated_data['queue']
        workflow_name = validated_data['workflow_name']
        steps = validated_data['steps']

        batch_id = uuid.uuid4()
        step_to_job_map = {}

        with transaction.atomic():
            # Step 1: Create all jobs
            for step in steps:
                has_deps = bool(step.get('depends_on'))
                job = Job.objects.create(
                    project=project,
                    queue=queue,
                    name=f"{workflow_name} - {step['name']}",
                    job_type=Job.JobType.WORKFLOW_STEP,
                    handler=step['handler'],
                    status=Job.Status.PENDING if has_deps else Job.Status.QUEUED,
                    payload=step['payload'],
                    batch_id=batch_id,
                    priority=queue.priority
                )
                step_to_job_map[step['step_id']] = job

            # Step 2: Link dependencies
            for step in steps:
                job = step_to_job_map[step['step_id']]
                for parent_step_id in step.get('depends_on', []):
                    parent_job = step_to_job_map.get(parent_step_id)
                    if parent_job:
                        JobDependency.objects.create(job=job, depends_on=parent_job)

        return {
            'workflow_id': batch_id,
            'workflow_name': workflow_name,
            'total_steps': len(steps),
            'job_ids': {k: str(v.id) for k, v in step_to_job_map.items()}
        }


class ScheduledJobSerializer(serializers.ModelSerializer):
    queue_name = serializers.ReadOnlyField(source='queue.name')

    class Meta:
        model = ScheduledJob
        fields = [
            'id', 'project', 'queue', 'queue_name', 'name', 'handler',
            'cron_expression', 'timezone', 'payload', 'priority',
            'is_enabled', 'last_run_at', 'next_run_at', 'created_at'
        ]

    def create(self, validated_data):
        cron_expr = validated_data.get('cron_expression')
        validated_data['next_run_at'] = get_next_cron_run(cron_expr)
        return super().create(validated_data)


class DeadLetterQueueEntrySerializer(serializers.ModelSerializer):
    job_name = serializers.ReadOnlyField(source='job.name')
    job_payload = serializers.ReadOnlyField(source='job.payload')
    original_queue_name = serializers.ReadOnlyField(source='original_queue.name')

    class Meta:
        model = DeadLetterQueueEntry
        fields = [
            'id', 'job', 'job_name', 'job_payload', 'original_queue',
            'original_queue_name', 'failed_at', 'failure_reason',
            'failure_category', 'ai_summary', 'replayed_at', 'replay_count'
        ]


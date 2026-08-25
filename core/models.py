import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
import hashlib
import secrets

class Organization(models.Model):
    """Multi-tenant organization holding multiple projects."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organizations'
        ordering = ['name']

    def __str__(self):
        return self.name


class Project(models.Model):
    """Project workspace grouping job queues, API keys, and configurations."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='projects')
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'projects'
        unique_together = ('organization', 'slug')
        ordering = ['name']

    def __str__(self):
        return f"{self.organization.name} / {self.name}"


class ProjectMembership(models.Model):
    """User membership and role within a project (RBAC)."""
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        DEVELOPER = 'DEVELOPER', 'Developer'
        VIEWER = 'VIEWER', 'Viewer'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_memberships')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DEVELOPER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'project_memberships'
        unique_together = ('user', 'project')


class APIKey(models.Model):
    """Secure API key for programmatic API authentication."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='api_keys')
    name = models.CharField(max_length=255)
    key_prefix = models.CharField(max_length=16, db_index=True)
    key_hash = models.CharField(max_length=128, db_index=True)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_keys'

    @classmethod
    def generate_key(cls, project, name):
        """Generates a raw key (returned once) and persists the hash."""
        raw_token = f"djs_{secrets.token_urlsafe(32)}"
        prefix = raw_token[:10]
        hashed = hashlib.sha256(raw_token.encode()).hexdigest()
        api_key = cls.objects.create(
            project=project,
            name=name,
            key_prefix=prefix,
            key_hash=hashed,
            is_active=True
        )
        return api_key, raw_token

    @classmethod
    def verify_key(cls, raw_token):
        """Verifies raw key against persisted hashes."""
        if not raw_token or not raw_token.startswith('djs_'):
            return None
        hashed = hashlib.sha256(raw_token.encode()).hexdigest()
        try:
            key_obj = cls.objects.select_related('project').get(key_hash=hashed, is_active=True)
            key_obj.last_used_at = timezone.now()
            key_obj.save(update_fields=['last_used_at'])
            return key_obj
        except cls.DoesNotExist:
            return None


class RetryPolicy(models.Model):
    """Configurable retry strategies for queues and individual jobs."""
    class Strategy(models.TextChoices):
        FIXED = 'FIXED', 'Fixed Delay'
        LINEAR_BACKOFF = 'LINEAR_BACKOFF', 'Linear Backoff'
        EXPONENTIAL_BACKOFF = 'EXPONENTIAL_BACKOFF', 'Exponential Backoff'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='retry_policies')
    name = models.CharField(max_length=255)
    strategy = models.CharField(max_length=30, choices=Strategy.choices, default=Strategy.EXPONENTIAL_BACKOFF)
    max_retries = models.PositiveIntegerField(default=3)
    initial_interval_seconds = models.PositiveIntegerField(default=5)
    max_interval_seconds = models.PositiveIntegerField(default=3600)
    backoff_multiplier = models.FloatField(default=2.0)
    jitter = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'retry_policies'

    def __str__(self):
        return f"{self.name} ({self.strategy})"


class Queue(models.Model):
    """Job Queue with priority, concurrency limits, rate limiting, and state."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='queues')
    name = models.CharField(max_length=255)
    priority = models.PositiveIntegerField(default=10, help_text="Higher value = higher processing priority (1-100)")
    concurrency_limit = models.PositiveIntegerField(default=10, help_text="Max concurrent running jobs across worker fleet")
    rate_limit_per_second = models.PositiveIntegerField(default=0, help_text="0 = unlimited")
    burst_limit = models.PositiveIntegerField(default=0)
    is_paused = models.BooleanField(default=False)
    default_retry_policy = models.ForeignKey(RetryPolicy, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'queues'
        unique_together = ('project', 'name')
        ordering = ['-priority', 'name']

    def __str__(self):
        return f"{self.project.name}:{self.name}"

    @property
    def active_jobs_count(self):
        return self.jobs.filter(status='RUNNING').count()

    @property
    def queued_jobs_count(self):
        return self.jobs.filter(status='QUEUED').count()


class Worker(models.Model):
    """Distributed Worker node registration, heartbeat, and metrics."""
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        PAUSED = 'PAUSED', 'Paused'
        SHUTTING_DOWN = 'SHUTTING_DOWN', 'Shutting Down'
        DEAD = 'DEAD', 'Dead / Unresponsive'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hostname = models.CharField(max_length=255)
    pid = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    concurrency = models.PositiveIntegerField(default=4)
    current_running_jobs = models.PositiveIntegerField(default=0)
    total_processed_jobs = models.PositiveIntegerField(default=0)
    total_failed_jobs = models.PositiveIntegerField(default=0)
    cpu_usage_pct = models.FloatField(default=0.0)
    memory_usage_mb = models.FloatField(default=0.0)
    queues_subscribed = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'workers'
        ordering = ['-last_heartbeat_at']

    def __str__(self):
        return f"Worker-{str(self.id)[:8]} ({self.hostname}:{self.pid})"

    @property
    def is_alive(self):
        threshold = timezone.now() - timezone.timedelta(seconds=30)
        return self.last_heartbeat_at >= threshold and self.status != self.Status.DEAD


class WorkerHeartbeat(models.Model):
    """Time-series telemetry heartbeats from workers."""
    id = models.BigAutoField(primary_key=True)
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='heartbeats')
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    running_job_count = models.PositiveIntegerField(default=0)
    completed_job_count = models.PositiveIntegerField(default=0)
    failed_job_count = models.PositiveIntegerField(default=0)
    cpu_usage_pct = models.FloatField(default=0.0)
    memory_usage_mb = models.FloatField(default=0.0)

    class Meta:
        db_table = 'worker_heartbeats'
        ordering = ['-timestamp']


class Job(models.Model):
    """Core Job entity with full lifecycle, payload, locks, and telemetry."""
    class JobType(models.TextChoices):
        IMMEDIATE = 'IMMEDIATE', 'Immediate'
        DELAYED = 'DELAYED', 'Delayed'
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        RECURRING = 'RECURRING', 'Recurring (Cron)'
        BATCH = 'BATCH', 'Batch Parent'
        BATCH_CHILD = 'BATCH_CHILD', 'Batch Child'
        WORKFLOW_STEP = 'WORKFLOW_STEP', 'Workflow Step (DAG)'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending (Dependencies Unmet)'
        QUEUED = 'QUEUED', 'Queued'
        CLAIMED = 'CLAIMED', 'Claimed by Worker'
        RUNNING = 'RUNNING', 'Running'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        RETRYING = 'RETRYING', 'Retrying'
        DEAD_LETTER = 'DEAD_LETTER', 'Dead Letter'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='jobs')
    queue = models.ForeignKey(Queue, on_delete=models.CASCADE, related_name='jobs')
    name = models.CharField(max_length=255)
    job_type = models.CharField(max_length=30, choices=JobType.choices, default=JobType.IMMEDIATE)
    handler = models.CharField(max_length=255, default='mock_task', help_text="Registered execution handler function")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    priority = models.PositiveIntegerField(default=10)
    
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    error_stack = models.TextField(blank=True, null=True)
    
    idempotency_key = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    scheduled_at = models.DateTimeField(default=timezone.now, db_index=True)
    timeout_seconds = models.PositiveIntegerField(default=300)
    max_retries = models.PositiveIntegerField(default=3)
    current_attempt = models.PositiveIntegerField(default=0)
    
    retry_policy = models.ForeignKey(RetryPolicy, on_delete=models.SET_NULL, null=True, blank=True)
    claimed_by_worker = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name='claimed_jobs')
    claimed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    parent_job = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_jobs')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'jobs'
        indexes = [
            models.Index(fields=['queue', 'status', '-priority', 'scheduled_at'], name='job_claim_idx'),
            models.Index(fields=['project', 'status'], name='job_proj_status_idx'),
            models.Index(fields=['status', 'scheduled_at'], name='job_status_sched_idx'),
            models.Index(fields=['batch_id'], name='job_batch_idx'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Job-{str(self.id)[:8]}: {self.name} [{self.status}]"

    @property
    def duration_ms(self):
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return None


class JobDependency(models.Model):
    """Directed Acyclic Graph (DAG) dependencies between jobs."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='dependencies')
    depends_on = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='dependents')
    required_status = models.CharField(max_length=20, default='COMPLETED')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'job_dependencies'
        unique_together = ('job', 'depends_on')

    def __str__(self):
        return f"{self.job.name} -> depends on {self.depends_on.name}"


class JobExecution(models.Model):
    """Historical record for every execution attempt of a job."""
    class ExecutionStatus(models.TextChoices):
        RUNNING = 'RUNNING', 'Running'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        TIMED_OUT = 'TIMED_OUT', 'Timed Out'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='executions')
    worker = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name='executions')
    attempt_number = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=ExecutionStatus.choices, default=ExecutionStatus.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    exit_code = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default='')
    error_stack = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'job_executions'
        ordering = ['attempt_number']

    def __str__(self):
        return f"Execution #{self.attempt_number} for Job-{str(self.job.id)[:8]}"


class JobLog(models.Model):
    """Detailed streaming execution logs for a job."""
    class Level(models.TextChoices):
        INFO = 'INFO', 'Info'
        WARN = 'WARN', 'Warning'
        ERROR = 'ERROR', 'Error'
        DEBUG = 'DEBUG', 'Debug'

    id = models.BigAutoField(primary_key=True)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='logs')
    execution = models.ForeignKey(JobExecution, on_delete=models.CASCADE, null=True, blank=True, related_name='logs')
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'job_logs'
        ordering = ['timestamp', 'id']

    def __str__(self):
        return f"[{self.level}] {self.timestamp.strftime('%H:%M:%S')} - {self.message[:60]}"


class ScheduledJob(models.Model):
    """Recurring cron job definitions."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='scheduled_jobs')
    queue = models.ForeignKey(Queue, on_delete=models.CASCADE, related_name='scheduled_jobs')
    name = models.CharField(max_length=255)
    handler = models.CharField(max_length=255, default='mock_task')
    cron_expression = models.CharField(max_length=100, help_text="Standard 5-part cron syntax e.g. */10 * * * *")
    timezone = models.CharField(max_length=50, default='UTC')
    payload = models.JSONField(default=dict, blank=True)
    priority = models.PositiveIntegerField(default=10)
    is_enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scheduled_jobs'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.cron_expression})"


class DeadLetterQueueEntry(models.Model):
    """Dead Letter Queue (DLQ) entries for exhausted or fatal jobs."""
    class Category(models.TextChoices):
        TIMEOUT = 'TIMEOUT', 'Execution Timeout'
        CRASH = 'CRASH', 'Process Crash / OOM'
        EXCEPTION = 'EXCEPTION', 'Unhandled Exception'
        RATE_LIMIT = 'RATE_LIMIT', 'Rate Limit Exceeded'
        DEPENDENCY_FAILED = 'DEPENDENCY_FAILED', 'Parent Dependency Failed'
        UNHANDLED = 'UNHANDLED', 'Other Failure'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='dlq_entry')
    original_queue = models.ForeignKey(Queue, on_delete=models.CASCADE, related_name='dlq_entries')
    failed_at = models.DateTimeField(auto_now_add=True)
    failure_reason = models.TextField()
    failure_category = models.CharField(max_length=30, choices=Category.choices, default=Category.EXCEPTION)
    ai_summary = models.TextField(blank=True, default='', help_text="AI-generated failure root-cause analysis")
    replayed_at = models.DateTimeField(null=True, blank=True)
    replay_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'dead_letter_queue_entries'
        ordering = ['-failed_at']

    def __str__(self):
        return f"DLQ Entry for Job-{str(self.job.id)[:8]} ({self.failure_category})"


class DistributedLock(models.Model):
    """Database-backed distributed lock with TTL expiration."""
    lock_key = models.CharField(max_length=255, primary_key=True)
    holder_id = models.CharField(max_length=255)
    acquired_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'distributed_locks'

    def __str__(self):
        return f"Lock:{self.lock_key} (held by {self.holder_id})"


class RateLimitBucket(models.Model):
    """Token bucket state per queue for distributed rate limiting."""
    queue = models.OneToOneField(Queue, on_delete=models.CASCADE, primary_key=True, related_name='rate_limit_bucket')
    tokens = models.FloatField(default=0.0)
    last_refill_timestamp = models.FloatField(default=0.0)

    class Meta:
        db_table = 'rate_limit_buckets'


from django.contrib import admin
from core.models import (
    Organization, Project, ProjectMembership, APIKey,
    RetryPolicy, Queue, Worker, WorkerHeartbeat,
    Job, JobDependency, JobExecution, JobLog,
    ScheduledJob, DeadLetterQueueEntry, DistributedLock, RateLimitBucket
)

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'created_at']
    search_fields = ['name', 'slug']


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'slug', 'is_active', 'created_at']
    list_filter = ['is_active', 'organization']
    search_fields = ['name', 'slug']


@admin.register(Queue)
class QueueAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'priority', 'concurrency_limit', 'rate_limit_per_second', 'is_paused', 'created_at']
    list_filter = ['is_paused', 'project']
    search_fields = ['name']


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'queue', 'status', 'priority', 'current_attempt', 'max_retries', 'created_at']
    list_filter = ['status', 'job_type', 'queue']
    search_fields = ['name', 'idempotency_key', 'id']


@admin.register(JobExecution)
class JobExecutionAdmin(admin.ModelAdmin):
    list_display = ['job', 'attempt_number', 'status', 'duration_ms', 'started_at', 'finished_at']
    list_filter = ['status']


@admin.register(JobLog)
class JobLogAdmin(admin.ModelAdmin):
    list_display = ['job', 'timestamp', 'level', 'message']
    list_filter = ['level']


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ['hostname', 'pid', 'status', 'concurrency', 'current_running_jobs', 'last_heartbeat_at']
    list_filter = ['status']


@admin.register(ScheduledJob)
class ScheduledJobAdmin(admin.ModelAdmin):
    list_display = ['name', 'queue', 'cron_expression', 'is_enabled', 'next_run_at', 'last_run_at']
    list_filter = ['is_enabled']


@admin.register(DeadLetterQueueEntry)
class DeadLetterQueueAdmin(admin.ModelAdmin):
    list_display = ['job', 'original_queue', 'failure_category', 'failed_at', 'replay_count']
    list_filter = ['failure_category']


@admin.register(RetryPolicy)
class RetryPolicyAdmin(admin.ModelAdmin):
    list_display = ['name', 'project', 'strategy', 'max_retries', 'initial_interval_seconds']


admin.site.register(APIKey)
admin.site.register(ProjectMembership)
admin.site.register(JobDependency)
admin.site.register(WorkerHeartbeat)
admin.site.register(DistributedLock)
admin.site.register(RateLimitBucket)


from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from core.models import (
    Job, Queue, Worker, ScheduledJob, DeadLetterQueueEntry,
    Project, JobExecution, JobLog
)

def overview(request):
    """Main dashboard overview with telemetry, queue backlog, and recent activities."""
    now = timezone.now()
    threshold = now - timezone.timedelta(seconds=30)

    active_workers = Worker.objects.filter(last_heartbeat_at__gte=threshold, status=Worker.Status.ACTIVE).count()
    queues = Queue.objects.all()
    recent_jobs = Job.objects.all().select_related('queue', 'project').order_by('-created_at')[:10]
    dlq_count = DeadLetterQueueEntry.objects.count()

    total_jobs = Job.objects.count()
    completed_jobs = Job.objects.filter(status=Job.Status.COMPLETED).count()
    running_jobs = Job.objects.filter(status=Job.Status.RUNNING).count()
    queued_jobs = Job.objects.filter(status=Job.Status.QUEUED).count()
    failed_jobs = Job.objects.filter(status__in=[Job.Status.FAILED, Job.Status.DEAD_LETTER]).count()

    context = {
        'active_workers': active_workers,
        'queues': queues,
        'recent_jobs': recent_jobs,
        'dlq_count': dlq_count,
        'total_jobs': total_jobs,
        'completed_jobs': completed_jobs,
        'running_jobs': running_jobs,
        'queued_jobs': queued_jobs,
        'failed_jobs': failed_jobs,
        'current_page': 'overview'
    }
    return render(request, 'dashboard/index.html', context)


def queues_view(request):
    """Queue management and live controls."""
    queues = Queue.objects.all().prefetch_related('jobs')
    projects = Project.objects.all()
    context = {
        'queues': queues,
        'projects': projects,
        'current_page': 'queues'
    }
    return render(request, 'dashboard/queues.html', context)


def jobs_view(request):
    """Job explorer with filters, search, and live auto-refresh."""
    queues = Queue.objects.all()
    projects = Project.objects.all()
    context = {
        'queues': queues,
        'projects': projects,
        'current_page': 'jobs'
    }
    return render(request, 'dashboard/jobs.html', context)


def job_detail_view(request, job_id):
    """Deep inspection for a specific job: timeline, logs, retries, and DAG dependencies."""
    job = get_object_or_404(Job.objects.select_related('queue', 'project', 'claimed_by_worker', 'retry_policy'), id=job_id)
    executions = job.executions.all().select_related('worker').order_by('attempt_number')
    logs = job.logs.all().order_by('timestamp', 'id')
    dependencies = job.dependencies.all().select_related('depends_on')
    dependents = job.dependents.all().select_related('job')

    context = {
        'job': job,
        'executions': executions,
        'logs': logs,
        'dependencies': dependencies,
        'dependents': dependents,
        'current_page': 'jobs'
    }
    return render(request, 'dashboard/job_detail.html', context)


def workflows_view(request):
    """Interactive DAG workflow manager and visualizer."""
    projects = Project.objects.all()
    queues = Queue.objects.all()
    context = {
        'projects': projects,
        'queues': queues,
        'current_page': 'workflows'
    }
    return render(request, 'dashboard/workflows.html', context)


def dlq_view(request):
    """Dead Letter Queue inspection and AI root cause summaries."""
    entries = DeadLetterQueueEntry.objects.all().select_related('job', 'original_queue').order_by('-failed_at')
    context = {
        'entries': entries,
        'current_page': 'dlq'
    }
    return render(request, 'dashboard/dlq.html', context)


def schedules_view(request):
    """Recurring cron jobs and scheduled tasks."""
    schedules = ScheduledJob.objects.all().select_related('queue', 'project').order_by('name')
    projects = Project.objects.all()
    queues = Queue.objects.all()
    context = {
        'schedules': schedules,
        'projects': projects,
        'queues': queues,
        'current_page': 'schedules'
    }
    return render(request, 'dashboard/schedules.html', context)


def workers_view(request):
    """Worker fleet telemetry, heartbeats, and cluster topology."""
    workers = Worker.objects.all().order_by('-last_heartbeat_at')
    context = {
        'workers': workers,
        'current_page': 'workers'
    }
    return render(request, 'dashboard/workers.html', context)


def analytics_view(request):
    """System-wide throughput and latency analytics."""
    context = {
        'current_page': 'analytics'
    }
    return render(request, 'dashboard/analytics.html', context)


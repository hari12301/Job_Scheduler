import logging
from django.utils import timezone
from core.models import Job, JobDependency, DeadLetterQueueEntry
from core.engine.ai_summarizer import generate_ai_failure_summary

logger = logging.getLogger(__name__)

def resolve_workflow_dependencies():
    """
    Scans all PENDING workflow jobs and unlocks those whose parent dependencies are satisfied.
    If any parent job failed, marks dependent child jobs as FAILED.
    """
    pending_jobs = Job.objects.filter(status=Job.Status.PENDING).prefetch_related('dependencies__depends_on')
    unlocked_count = 0
    failed_count = 0

    for job in pending_jobs:
        dependencies = list(job.dependencies.all())
        if not dependencies:
            # No dependencies, move to QUEUED
            job.status = Job.Status.QUEUED
            job.save(update_fields=['status'])
            unlocked_count += 1
            continue

        all_completed = True
        parent_failed = False
        failed_parent_name = ""

        for dep in dependencies:
            parent = dep.depends_on
            if parent.status in [Job.Status.FAILED, Job.Status.DEAD_LETTER, Job.Status.CANCELLED]:
                parent_failed = True
                failed_parent_name = parent.name
                break
            elif parent.status != Job.Status.COMPLETED:
                all_completed = False

        if parent_failed:
            # Mark child as failed due to parent dependency
            job.status = Job.Status.FAILED
            job.error_message = f"Upstream dependency failed: '{failed_parent_name}'"
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'error_message', 'completed_at'])

            # Route to DLQ
            cat, summary = generate_ai_failure_summary(job.name, job.error_message, "")
            DeadLetterQueueEntry.objects.update_or_create(
                job=job,
                defaults={
                    'original_queue': job.queue,
                    'failure_reason': job.error_message,
                    'failure_category': cat,
                    'ai_summary': summary
                }
            )
            failed_count += 1

        elif all_completed:
            # All parents successfully completed, unlock this job!
            job.status = Job.Status.QUEUED
            job.save(update_fields=['status'])
            unlocked_count += 1
            logger.info(f"DAG Engine: Unlocked job {job.name} (ID: {job.id})")

    return unlocked_count, failed_count


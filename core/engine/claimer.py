import logging
from django.db import transaction, connection
from django.utils import timezone
from core.models import Job, Queue, Worker
from core.engine.rate_limiter import check_and_consume_rate_limit

logger = logging.getLogger(__name__)

def claim_jobs_for_worker(worker: Worker, queue_names=None, limit=1):
    """
    Atomically claims up to `limit` jobs for the given worker.
    Uses PostgreSQL 'SELECT ... FOR UPDATE SKIP LOCKED' to prevent race conditions.
    Enforces Queue priority, queue pause state, queue concurrency limits, and rate limits.
    """
    now = timezone.now()
    claimed_jobs = []

    # Find candidate queues
    queue_query = Queue.objects.filter(is_paused=False)
    if queue_names:
        queue_query = queue_query.filter(name__in=queue_names)
    
    # Process queues in order of highest priority first
    queues = list(queue_query.order_by('-priority', 'name'))

    for queue in queues:
        if len(claimed_jobs) >= limit:
            break

        # Check queue concurrency limit
        current_active = Job.objects.filter(
            queue=queue,
            status__in=[Job.Status.CLAIMED, Job.Status.RUNNING]
        ).count()

        available_concurrency = queue.concurrency_limit - current_active
        if available_concurrency <= 0:
            continue  # Queue is currently at max concurrency capacity

        # Check queue rate limiting (Token Bucket)
        if queue.rate_limit_per_second > 0:
            if not check_and_consume_rate_limit(queue):
                continue  # Rate limit exceeded for this queue tick

        batch_size = min(limit - len(claimed_jobs), available_concurrency)

        try:
            with transaction.atomic():
                # Check DB vendor
                if connection.vendor == 'postgresql':
                    raw_sql = """
                        SELECT id FROM jobs
                        WHERE queue_id = %s
                          AND status = %s
                          AND scheduled_at <= %s
                        ORDER BY priority DESC, scheduled_at ASC
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                    """
                    with connection.cursor() as cursor:
                        cursor.execute(raw_sql, [queue.id, Job.Status.QUEUED, now, batch_size])
                        job_ids = [row[0] for row in cursor.fetchall()]
                else:
                    # SQLite / other fallback for unit testing
                    job_ids = list(
                        Job.objects.select_for_update(skip_locked=True)
                        .filter(
                            queue=queue,
                            status=Job.Status.QUEUED,
                            scheduled_at__lte=now
                        )
                        .order_by('-priority', 'scheduled_at')
                        .values_list('id', flat=True)[:batch_size]
                    )

                if job_ids:
                    # Atomically update claimed status
                    jobs_to_claim = Job.objects.filter(id__in=job_ids)
                    for job in jobs_to_claim:
                        job.status = Job.Status.CLAIMED
                        job.claimed_by_worker = worker
                        job.claimed_at = now
                        job.save(update_fields=['status', 'claimed_by_worker', 'claimed_at'])
                        claimed_jobs.append(job)

        except Exception as e:
            logger.error(f"Error claiming jobs for queue {queue.name}: {e}", exc_info=True)

    return claimed_jobs


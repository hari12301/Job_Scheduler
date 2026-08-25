import random
from django.utils import timezone
from datetime import timedelta
from core.models import RetryPolicy, Job

def calculate_next_retry(job: Job) -> timezone.datetime:
    """
    Calculates next execution datetime for a failed job based on its RetryPolicy or defaults.
    """
    policy = job.retry_policy
    if not policy and job.queue.default_retry_policy:
        policy = job.queue.default_retry_policy

    attempt = job.current_attempt  # 1-indexed for the failure attempt

    if not policy:
        # Default exponential backoff
        strategy = RetryPolicy.Strategy.EXPONENTIAL_BACKOFF
        initial = 5
        max_interval = 3600
        multiplier = 2.0
        use_jitter = True
    else:
        strategy = policy.strategy
        initial = policy.initial_interval_seconds
        max_interval = policy.max_interval_seconds
        multiplier = policy.backoff_multiplier
        use_jitter = policy.jitter

    if strategy == RetryPolicy.Strategy.FIXED:
        delay = initial
    elif strategy == RetryPolicy.Strategy.LINEAR_BACKOFF:
        delay = initial * attempt
    elif strategy == RetryPolicy.Strategy.EXPONENTIAL_BACKOFF:
        delay = initial * (multiplier ** (attempt - 1))
    else:
        delay = initial

    # Clamp at maximum interval
    delay = min(delay, max_interval)

    # Apply jitter
    if use_jitter and delay > 0:
        jitter_factor = random.uniform(0.85, 1.15)
        delay = delay * jitter_factor

    return timezone.now() + timedelta(seconds=delay)


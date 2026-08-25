import time
from django.db import transaction
from core.models import Queue, RateLimitBucket

def check_and_consume_rate_limit(queue: Queue, tokens_needed: float = 1.0) -> bool:
    """
    Distributed Token Bucket algorithm for queue-level rate limiting.
    Refills tokens based on elapsed time and rate_limit_per_second.
    Returns True if rate limit is within capacity and tokens consumed, False otherwise.
    """
    if queue.rate_limit_per_second <= 0:
        return True  # No rate limit set

    now = time.time()
    rate = float(queue.rate_limit_per_second)
    burst = float(queue.burst_limit if queue.burst_limit > 0 else queue.rate_limit_per_second)

    with transaction.atomic():
        bucket, created = RateLimitBucket.objects.select_for_update().get_or_create(
            queue=queue,
            defaults={'tokens': burst, 'last_refill_timestamp': now}
        )

        # Refill tokens based on elapsed time
        elapsed = now - bucket.last_refill_timestamp
        if elapsed > 0:
            new_tokens = min(burst, bucket.tokens + (elapsed * rate))
            bucket.tokens = new_tokens
            bucket.last_refill_timestamp = now

        if bucket.tokens >= tokens_needed:
            bucket.tokens -= tokens_needed
            bucket.save(update_fields=['tokens', 'last_refill_timestamp'])
            return True
        else:
            bucket.save(update_fields=['tokens', 'last_refill_timestamp'])
            return False


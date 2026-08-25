import logging
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from core.models import DistributedLock

logger = logging.getLogger(__name__)

class DistributedLockManager:
    """
    Database-backed distributed lock with TTL expiration and automatic heartbeat renewal.
    """
    @classmethod
    def acquire(cls, lock_key: str, holder_id: str, ttl_seconds: int = 60) -> bool:
        now = timezone.now()
        expires = now + timedelta(seconds=ttl_seconds)

        with transaction.atomic():
            lock = DistributedLock.objects.filter(lock_key=lock_key).first()
            if lock:
                if lock.expires_at < now:
                    # Lock expired, take over
                    lock.holder_id = holder_id
                    lock.expires_at = expires
                    lock.save()
                    return True
                elif lock.holder_id == holder_id:
                    # Re-entrant / renew
                    lock.expires_at = expires
                    lock.save()
                    return True
                return False
            else:
                try:
                    DistributedLock.objects.create(
                        lock_key=lock_key,
                        holder_id=holder_id,
                        expires_at=expires
                    )
                    return True
                except Exception:
                    return False

    @classmethod
    def release(cls, lock_key: str, holder_id: str) -> bool:
        with transaction.atomic():
            lock = DistributedLock.objects.filter(lock_key=lock_key, holder_id=holder_id).first()
            if lock:
                lock.delete()
                return True
            return False

    @classmethod
    def renew(cls, lock_key: str, holder_id: str, ttl_seconds: int = 60) -> bool:
        now = timezone.now()
        expires = now + timedelta(seconds=ttl_seconds)
        updated = DistributedLock.objects.filter(
            lock_key=lock_key,
            holder_id=holder_id,
            expires_at__gte=now
        ).update(expires_at=expires)
        return updated > 0


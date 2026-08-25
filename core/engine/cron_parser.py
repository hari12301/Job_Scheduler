import datetime
from django.utils import timezone
try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False

def get_next_cron_run(cron_expression: str, start_time=None) -> datetime.datetime:
    """
    Computes the next execution datetime from a standard 5-part cron string:
    'minute hour day_of_month month day_of_week'
    """
    if not start_time:
        start_time = timezone.now()

    if HAS_CRONITER:
        try:
            itr = croniter(cron_expression, start_time)
            next_dt = itr.get_next(datetime.datetime)
            if timezone.is_naive(next_dt):
                next_dt = timezone.make_aware(next_dt)
            return next_dt
        except Exception:
            pass

    # Pure Python Cron Fallback parser for standard patterns
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        # Default to +5 minutes if invalid syntax
        return start_time + datetime.timedelta(minutes=5)

    minute_str, hour_str, dom_str, month_str, dow_str = parts

    # Parse interval minute (e.g. */5, */10, */15, */30)
    current = start_time.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)

    for _ in range(60 * 24 * 365):  # search up to 1 year ahead
        m_match = match_cron_field(minute_str, current.minute, 0, 59)
        h_match = match_cron_field(hour_str, current.hour, 0, 23)
        dom_match = match_cron_field(dom_str, current.day, 1, 31)
        mon_match = match_cron_field(month_str, current.month, 1, 12)
        dow_match = match_cron_field(dow_str, (current.weekday() + 1) % 7, 0, 6)

        if m_match and h_match and dom_match and mon_match and dow_match:
            return current

        current += datetime.timedelta(minutes=1)

    return start_time + datetime.timedelta(minutes=5)

def match_cron_field(field_pattern: str, val: int, min_val: int, max_val: int) -> bool:
    if field_pattern == '*':
        return True
    if field_pattern.startswith('*/'):
        step = int(field_pattern[2:])
        return val % step == 0
    if ',' in field_pattern:
        subfields = [int(x) for x in field_pattern.split(',') if x.isdigit()]
        return val in subfields
    if '-' in field_pattern:
        start, end = [int(x) for x in field_pattern.split('-') if x.isdigit()]
        return start <= val <= end
    if field_pattern.isdigit():
        return val == int(field_pattern)
    return False


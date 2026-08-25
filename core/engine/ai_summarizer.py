import re
from core.models import DeadLetterQueueEntry

def generate_ai_failure_summary(job_name: str, error_message: str, error_stack: str) -> tuple[str, str]:
    """
    Analyzes error messages and stack traces to produce:
    1. failure_category (Category enum)
    2. ai_summary: Structured root-cause explanation and suggested fix.
    """
    combined_text = f"{error_message or ''}\n{error_stack or ''}"
    
    category = DeadLetterQueueEntry.Category.EXCEPTION
    summary_lines = []

    if re.search(r'(timed? ?out|TimeoutError|ConnectTimeout|ReadTimeout)', combined_text, re.I):
        category = DeadLetterQueueEntry.Category.TIMEOUT
        summary_lines.append("🛑 **Root Cause**: Job execution exceeded the configured timeout threshold or encountered an upstream network timeout.")
        summary_lines.append("💡 **Actionable Suggestion**: Increase `timeout_seconds` on the job configuration or check latency/availability of the upstream endpoint.")
    
    elif re.search(r'(ConnectionRefused|NewConnectionError|Failed to establish a new connection|ECONNREFUSED)', combined_text, re.I):
        category = DeadLetterQueueEntry.Category.CRASH
        summary_lines.append("🛑 **Root Cause**: Downstream network connection refused. The target server or database service is offline or unreachable.")
        summary_lines.append("💡 **Actionable Suggestion**: Verify the host/port in job payload, check network firewalls, and confirm the target service is running.")

    elif re.search(r'(429|Too Many Requests|RateLimit|QuotaExceeded)', combined_text, re.I):
        category = DeadLetterQueueEntry.Category.RATE_LIMIT
        summary_lines.append("🛑 **Root Cause**: Downstream API rate limit or quota exceeded (HTTP 429).")
        summary_lines.append("💡 **Actionable Suggestion**: Lower the queue's `rate_limit_per_second` setting or use an exponential backoff retry policy.")

    elif re.search(r'(OutOfMemory|MemoryError|killed|SIGKILL)', combined_text, re.I):
        category = DeadLetterQueueEntry.Category.CRASH
        summary_lines.append("🛑 **Root Cause**: Process exhausted system memory (OOM) or was terminated abruptly by the OS kernel.")
        summary_lines.append("💡 **Actionable Suggestion**: Batch large inputs into smaller chunks or increase worker memory allocation.")

    elif re.search(r'(KeyError|IndexError|TypeError|ValueError|JSONDecodeError)', combined_text, re.I):
        category = DeadLetterQueueEntry.Category.EXCEPTION
        summary_lines.append("🛑 **Root Cause**: Payload schema or data formatting discrepancy encountered during payload deserialization.")
        summary_lines.append("💡 **Actionable Suggestion**: Validate that the job payload conforms to the expected schema before dispatch.")

    elif re.search(r'(Dependency|Parent job failed)', combined_text, re.I):
        category = DeadLetterQueueEntry.Category.DEPENDENCY_FAILED
        summary_lines.append("🛑 **Root Cause**: An upstream parent job in the workflow DAG failed, aborting this dependent step.")
        summary_lines.append("💡 **Actionable Suggestion**: Inspect and replay the failed parent job in the workflow DAG.")

    else:
        category = DeadLetterQueueEntry.Category.UNHANDLED
        summary_lines.append(f"🛑 **Root Cause**: Unhandled exception during execution: `{error_message[:120] if error_message else 'Unknown error'}`.")
        summary_lines.append("💡 **Actionable Suggestion**: Check application logs and verify handler parameters.")

    # Extract failing file and line if present
    file_match = re.search(r'File "([^"]+)", line (\d+), in (\w+)', combined_text)
    if file_match:
        file_path, line_no, func_name = file_match.groups()
        summary_lines.append(f"📍 **Origin**: `{file_path}` line {line_no} in function `{func_name}()`")

    return category, "\n".join(summary_lines)


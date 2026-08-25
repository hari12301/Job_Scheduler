// Terminal Log Viewer Controller

function initTerminal(jobId) {
  const terminalBody = document.getElementById('terminal-logs-body');
  if (!terminalBody || !jobId) return;

  // Auto-scroll to bottom
  terminalBody.scrollTop = terminalBody.scrollHeight;

  // Live polling for in-progress jobs
  const statusBadge = document.getElementById('job-status-badge');
  if (statusBadge && (statusBadge.innerText.includes('RUNNING') || statusBadge.innerText.includes('QUEUED') || statusBadge.innerText.includes('CLAIMED'))) {
    setInterval(async () => {
      try {
        const logs = await apiRequest(`/api/v1/jobs/${jobId}/logs/`);
        terminalBody.innerHTML = '';
        logs.forEach(log => {
          const line = document.createElement('div');
          line.className = 'log-line';
          const timeStr = new Date(log.timestamp).toLocaleTimeString();
          line.innerHTML = `
            <span class="log-time">${timeStr}</span>
            <span class="log-level-${log.level}">[${log.level}]</span>
            <span class="log-msg">${escapeHtml(log.message)}</span>
          `;
          terminalBody.appendChild(line);
        });
        terminalBody.scrollTop = terminalBody.scrollHeight;
      } catch (e) {
        console.error("Log poll error", e);
      }
    }, 2000);
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.innerText = text;
  return div.innerHTML;
}


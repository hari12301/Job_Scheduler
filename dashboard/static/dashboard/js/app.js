// Distributed Scheduler Dashboard App JS

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  
  let icon = 'ℹ️';
  if (type === 'success') icon = '✅';
  if (type === 'error') icon = '🛑';
  if (type === 'warning') icon = '⚠️';

  toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// API Helper
async function apiRequest(url, method = 'GET', data = null) {
  const options = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken') || ''
    }
  };
  if (data && method !== 'GET') {
    options.body = JSON.stringify(data);
  }

  try {
    const res = await fetch(url, options);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || err.detail || 'API request failed');
    }
    return await res.json();
  } catch (error) {
    showToast(error.message, 'error');
    throw error;
  }
}

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

// Modal Helpers
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.add('active');
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.remove('active');
}

// Queue Actions
async function toggleQueuePause(queueId, currentPaused) {
  const endpoint = currentPaused ? `/api/v1/queues/${queueId}/resume/` : `/api/v1/queues/${queueId}/pause/`;
  try {
    await apiRequest(endpoint, 'POST');
    showToast(`Queue ${currentPaused ? 'resumed' : 'paused'} successfully.`, 'success');
    setTimeout(() => window.location.reload(), 500);
  } catch (e) {
    console.error(e);
  }
}

async function purgeQueue(queueId) {
  if (!confirm("Are you sure you want to purge all queued jobs from this queue?")) return;
  try {
    const res = await apiRequest(`/api/v1/queues/${queueId}/purge/`, 'POST');
    showToast(`Purged ${res.jobs_removed} pending jobs.`, 'success');
    setTimeout(() => window.location.reload(), 500);
  } catch (e) {
    console.error(e);
  }
}

// Job Actions
async function retryJob(jobId) {
  try {
    await apiRequest(`/api/v1/jobs/${jobId}/retry/`, 'POST');
    showToast("Job re-queued for execution.", 'success');
    setTimeout(() => window.location.reload(), 600);
  } catch (e) {
    console.error(e);
  }
}

async function cancelJob(jobId) {
  if (!confirm("Cancel this job execution?")) return;
  try {
    await apiRequest(`/api/v1/jobs/${jobId}/cancel/`, 'POST');
    showToast("Job cancelled.", 'warning');
    setTimeout(() => window.location.reload(), 600);
  } catch (e) {
    console.error(e);
  }
}

// DLQ Actions
async function replayDlqEntry(entryId) {
  try {
    await apiRequest(`/api/v1/dlq/${entryId}/replay/`, 'POST');
    showToast("Dead letter entry replayed successfully.", 'success');
    setTimeout(() => window.location.reload(), 600);
  } catch (e) {
    console.error(e);
  }
}

async function replayAllDlq() {
  if (!confirm("Replay ALL jobs in the Dead Letter Queue?")) return;
  try {
    const res = await apiRequest('/api/v1/dlq/replay_all/', 'POST');
    showToast(`Successfully replayed ${res.replayed_count} jobs.`, 'success');
    setTimeout(() => window.location.reload(), 600);
  } catch (e) {
    console.error(e);
  }
}

// Auto-Refresh
let autoRefreshTimer = null;
function toggleAutoRefresh(enable, intervalMs = 3000) {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  if (enable) {
    autoRefreshTimer = setInterval(() => {
      const liveElements = document.querySelectorAll('[data-live-poll]');
      if (liveElements.length > 0) {
        window.location.reload();
      }
    }, intervalMs);
  }
}


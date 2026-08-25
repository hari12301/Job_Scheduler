// Chart.js Telemetry & Throughput Visualizations

function initOverviewCharts() {
  const throughputCanvas = document.getElementById('throughputChart');
  const statusDonutCanvas = document.getElementById('statusDonutChart');

  if (throughputCanvas && window.Chart) {
    const labels = ['5m ago', '4m ago', '3m ago', '2m ago', '1m ago', 'now'];
    const completedData = [45, 52, 68, 74, 91, 84];
    const failedData = [2, 0, 3, 1, 4, 1];

    new Chart(throughputCanvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Completed Jobs',
            data: completedData,
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.35,
            pointRadius: 3
          },
          {
            label: 'Failed / Retried',
            data: failedData,
            borderColor: '#ef4444',
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            fill: true,
            tension: 0.35,
            pointRadius: 3
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: '#94a3b8', font: { size: 12 } }
          }
        },
        scales: {
          x: {
            grid: { color: '#1e293b' },
            ticks: { color: '#64748b' }
          },
          y: {
            grid: { color: '#1e293b' },
            ticks: { color: '#64748b' },
            beginAtZero: true
          }
        }
      }
    });
  }

  if (statusDonutCanvas && window.Chart) {
    new Chart(statusDonutCanvas, {
      type: 'doughnut',
      data: {
        labels: ['Completed', 'Queued', 'Running', 'Failed / DLQ'],
        datasets: [{
          data: [
            window.STATUS_COUNTS?.COMPLETED || 25,
            window.STATUS_COUNTS?.QUEUED || 8,
            window.STATUS_COUNTS?.RUNNING || 3,
            (window.STATUS_COUNTS?.FAILED || 0) + (window.STATUS_COUNTS?.DEAD_LETTER || 2)
          ],
          backgroundColor: ['#10b981', '#f59e0b', '#3b82f6', '#ef4444'],
          borderColor: '#111827',
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#94a3b8', font: { size: 11 } }
          }
        },
        cutout: '70%'
      }
    });
  }
}

document.addEventListener('DOMContentLoaded', initOverviewCharts);


from django.urls import path
from dashboard.views import (
    overview, queues_view, jobs_view, job_detail_view,
    workflows_view, dlq_view, schedules_view, workers_view, analytics_view
)

urlpatterns = [
    path('', overview, name='dashboard-overview'),
    path('queues/', queues_view, name='dashboard-queues'),
    path('jobs/', jobs_view, name='dashboard-jobs'),
    path('jobs/<uuid:job_id>/', job_detail_view, name='dashboard-job-detail'),
    path('workflows/', workflows_view, name='dashboard-workflows'),
    path('dlq/', dlq_view, name='dashboard-dlq'),
    path('schedules/', schedules_view, name='dashboard-schedules'),
    path('workers/', workers_view, name='dashboard-workers'),
    path('analytics/', analytics_view, name='dashboard-analytics'),
]


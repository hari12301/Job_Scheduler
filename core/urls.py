from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import (
    OrganizationViewSet, ProjectViewSet, RetryPolicyViewSet,
    QueueViewSet, JobViewSet, WorkflowViewSet, ScheduledJobViewSet,
    WorkerViewSet, DeadLetterQueueViewSet, SystemMetricsView
)

router = DefaultRouter()
router.register(r'organizations', OrganizationViewSet, basename='organization')
router.register(r'projects', ProjectViewSet, basename='project')
router.register(r'retry-policies', RetryPolicyViewSet, basename='retry-policy')
router.register(r'queues', QueueViewSet, basename='queue')
router.register(r'jobs', JobViewSet, basename='job')
router.register(r'workflows', WorkflowViewSet, basename='workflow')
router.register(r'schedules', ScheduledJobViewSet, basename='schedule')
router.register(r'workers', WorkerViewSet, basename='worker')
router.register(r'dlq', DeadLetterQueueViewSet, basename='dlq')

urlpatterns = [
    path('', include(router.urls)),
    path('metrics/', SystemMetricsView.as_view(), name='system-metrics'),
]


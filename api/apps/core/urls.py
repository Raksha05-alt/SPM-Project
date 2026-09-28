from django.urls import path

from apps.core.views import AuditLogListView

urlpatterns = [
    path("audit/", AuditLogListView.as_view(), name="audit-log"),
]

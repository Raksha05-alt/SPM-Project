from django.urls import path

from apps.notifications.views import NotificationList

urlpatterns = [path("notifications/", NotificationList.as_view(), name="notifications")]

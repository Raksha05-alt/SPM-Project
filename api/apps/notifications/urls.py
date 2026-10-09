from django.urls import path

from apps.notifications.views import MarkRead, NotificationList, UnreadCount

urlpatterns = [
    path("notifications/", NotificationList.as_view(), name="notifications"),
    path("notifications/unread-count/", UnreadCount.as_view(), name="notifications-unread"),
    path("notifications/<int:pk>/read/", MarkRead.as_view(), name="notification-read"),
]

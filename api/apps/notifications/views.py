from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import HasAnyRole
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer


class NotificationList(ListAPIView):
    permission_classes = [HasAnyRole, IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

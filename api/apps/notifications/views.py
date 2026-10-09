from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasAnyRole
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer


class NotificationList(ListAPIView):
    """SCRUM-82 AC1 / AC4 - my notifications, newest first; an empty list is not an error."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related("event")


class UnreadCount(APIView):
    permission_classes = [HasAnyRole, IsAuthenticated]

    def get(self, request):
        unread = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
        return Response({"unread": unread})


class MarkRead(APIView):
    """SCRUM-82 AC2 - opening a notification marks it read. Only the recipient's own."""

    permission_classes = [HasAnyRole, IsAuthenticated]

    def post(self, request, pk):
        notification = get_object_or_404(
            Notification.objects.select_related("event"), pk=pk, recipient=request.user
        )
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        unread = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
        return Response({**NotificationSerializer(notification).data, "unread": unread})

from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasAnyRole
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer
from apps.notifications.services import mark_read, unread_count


class NotificationList(ListAPIView):
    """SCRUM-82 AC1 - the signed-in user's own notices, most recent first."""

    permission_classes = [HasAnyRole, IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return (
            Notification.objects.filter(recipient=self.request.user)
            .select_related("event")
            .order_by("-created_at", "-pk")
        )


class UnreadCount(APIView):
    """SCRUM-82 AC2 - how many of the user's notices are still unread."""

    permission_classes = [HasAnyRole, IsAuthenticated]

    def get(self, request):
        return Response({"unread": unread_count(request.user)})


class MarkRead(APIView):
    """SCRUM-82 AC2 - opening a notice marks only that notice read.

    Idempotent. Another user's notice answers 404, as if it did not exist.
    """

    permission_classes = [HasAnyRole, IsAuthenticated]

    def post(self, request, pk):
        get_object_or_404(Notification, pk=pk, recipient=request.user)
        notice = mark_read(pk, request.user)
        data = NotificationSerializer(notice, context={"request": request}).data
        return Response({"notification": data, "unread": unread_count(request.user)})

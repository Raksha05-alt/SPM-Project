from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.models import AuditLog
from apps.core.permissions import IsInternalStaff
from apps.core.serializers import AuditLogSerializer


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    """Walking skeleton endpoint. Proves web -> api -> settings are wired up."""
    return Response({"status": "ok"})


class AuditLogPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class AuditLogListView(ListAPIView):
    """US-01.2 AC4 - makes the recorded refusals readable.

    Recording an attempt is only half of an audit trail; somebody has to be able
    to look at it. This endpoint is itself internal planning information, so it
    is restricted to ConnectSphere staff (AC2) and every refused attempt to read
    it is itself recorded.

    Read-only by design: an audit row that can be edited or deleted through the
    API is not evidence of anything.
    """

    serializer_class = AuditLogSerializer
    permission_classes = [IsInternalStaff]
    pagination_class = AuditLogPagination

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor").all()

        # ?refused_only=true narrows to refusals, which is the common case when
        # investigating "did anyone try to reach something they should not?"
        if self.request.query_params.get("refused_only", "").lower() in {"1", "true", "yes"}:
            queryset = queryset.filter(allowed=False)

        actor = self.request.query_params.get("actor")
        if actor and actor.isdigit():
            queryset = queryset.filter(actor_id=int(actor))

        return queryset

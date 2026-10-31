"""SCRUM-91 - Venue Staff maintain the room layout catalogue."""

from django.db import IntegrityError, transaction
from django.db.models import Max
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.accounts.models import INTERNAL_ROLES, Role
from apps.core.audit import record
from apps.core.permissions import HasAnyRole
from apps.venues.layouts import CODE_PATTERN, layout_usage
from apps.venues.models import LayoutType
from apps.venues.permissions import VENUE_EDITORS

# AC5 - internal users and Event Organisers read the catalogue; Attendees do not.
LAYOUT_READERS = INTERNAL_ROLES | {Role.EVENT_ORGANISER}


class LayoutTypeSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LayoutType
        fields = [
            "code",
            "name",
            "description",
            "is_active",
            "sort_order",
            "updated_by_name",
            "created_at",
            "updated_at",
        ]
        # Retire/reinstate are explicit actions; order follows creation.
        read_only_fields = ["is_active", "sort_order", "created_at", "updated_at"]
        extra_kwargs = {
            "code": {"validators": []},
            "name": {"error_messages": {"blank": "Enter a name for the layout."}},
        }

    def get_updated_by_name(self, obj) -> str | None:
        user = obj.updated_by
        return None if user is None else (user.get_full_name() or user.email)

    def validate_code(self, value):
        code = value.strip().upper()
        if self.instance is not None:
            # AC2 - the code identifies the layout on every record; it never changes.
            if code != self.instance.code:
                raise serializers.ValidationError("A layout's code cannot be changed.")
            return code
        if not CODE_PATTERN.match(code):
            raise serializers.ValidationError(
                "Use 2-20 capital letters, digits or underscores, starting with a letter."
            )
        if LayoutType.objects.filter(code=code).exists():
            raise serializers.ValidationError("A layout with this code already exists.")
        return code

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Enter a name for the layout.")
        clash = LayoutType.objects.filter(name__iexact=name)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A layout with this name already exists.")
        return name

    def validate_description(self, value):
        return value.strip()


class LayoutTypeViewSet(ModelViewSet):
    serializer_class = LayoutTypeSerializer
    # HasAnyRole first so that every refusal is audited (US-01.2 AC4).
    permission_classes = [HasAnyRole, IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    lookup_field = "code"
    queryset = LayoutType.objects.select_related("updated_by")

    @property
    def allowed_roles(self):
        if self.request.method in SAFE_METHODS:
            return LAYOUT_READERS
        return VENUE_EDITORS

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list" and self.request.query_params.get("active") == "true":
            queryset = queryset.filter(is_active=True)
        return queryset

    def _path(self, code=None, suffix=""):
        return f"/api/layouts/{code}/{suffix}" if code else "/api/layouts/"

    def perform_create(self, serializer):
        user = self.request.user
        try:
            with transaction.atomic():
                last = LayoutType.objects.aggregate(last=Max("sort_order"))["last"] or 0
                layout = serializer.save(sort_order=last + 1, updated_by=user)
        except IntegrityError:
            raise ValidationError(
                {"code": "A layout with this code or name already exists."}
            ) from None
        record(user, f"POST {self._path()}", allowed=True, obj=layout)

    def partial_update(self, request, *args, **kwargs):
        code = kwargs["code"]
        with transaction.atomic():
            layout = LayoutType.objects.select_for_update().get(pk=self.get_object().pk)
            serializer = self.get_serializer(layout, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            try:
                with transaction.atomic():
                    layout = serializer.save(updated_by=request.user)
            except IntegrityError:
                raise ValidationError({"name": "A layout with this name already exists."}) from None
            record(request.user, f"PATCH {self._path(code)}", allowed=True, obj=layout)
        return Response(self.get_serializer(layout).data)

    def destroy(self, request, *args, **kwargs):
        code = kwargs["code"]
        with transaction.atomic():
            # Exclusive lock: waits for any selection of this layout to commit.
            layout = LayoutType.objects.select_for_update().get(pk=self.get_object().pk)
            usage = layout_usage(layout.code)
            if any(usage.values()):
                # AC3 - a layout in use is kept; retire it instead.
                return Response(
                    {
                        "detail": (
                            f"{layout.name} is in use and cannot be deleted. "
                            "Retire it instead so it can no longer be chosen."
                        ),
                        "usage": usage,
                        "can_retire": layout.is_active,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            layout.delete()
        record(request.user, f"DELETE {self._path(code)}", allowed=True, detail=code)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _set_active(self, request, code, active):
        with transaction.atomic():
            layout = LayoutType.objects.select_for_update().get(pk=self.get_object().pk)
            if layout.is_active != active:
                layout.is_active = active
                layout.updated_by = request.user
                layout.save(update_fields=["is_active", "updated_by", "updated_at"])
            suffix = "reinstate/" if active else "retire/"
            record(request.user, f"POST {self._path(code, suffix)}", allowed=True, obj=layout)
        return Response(self.get_serializer(layout).data)

    @action(detail=True, methods=["post"])
    def retire(self, request, code=None):
        """AC3/AC4 - keep a layout on existing records but stop new selections."""
        return self._set_active(request, code, active=False)

    @action(detail=True, methods=["post"])
    def reinstate(self, request, code=None):
        return self._set_active(request, code, active=True)

"""G03: shared equipment records; workflow actions are delivered in later gates."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.statuses import EventStatus


class UnavailabilityCause(models.TextChoices):
    DAMAGED = "DAMAGED", "Damaged"
    MAINTENANCE = "MAINTENANCE", "Under maintenance"


class EquipmentRequestStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Requested"
    RESERVED = "RESERVED", "Reserved"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class ReservationStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    RELEASED = "RELEASED", "Released"


class TechnicalApprovalStatus(models.TextChoices):
    APPROVED = "APPROVED", "Approved"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class EquipmentHistoryAction(models.TextChoices):
    REQUESTED = "REQUESTED", "Requested"
    AMENDED = "AMENDED", "Amended"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"
    RESERVED = "RESERVED", "Reserved"
    RELEASED = "RELEASED", "Released"
    APPROVED = "APPROVED", "Technical approval recorded"
    SUPERSEDED = "SUPERSEDED", "Technical approval superseded"


class EquipmentType(TimeStampedModel):
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    total_quantity = models.PositiveIntegerField(default=0)
    in_service = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name

    @property
    def unavailable_quantity(self):
        if not self.pk:
            return 0
        return (
            self.unavailability_records.filter(restored_at__isnull=True).aggregate(
                quantity=Sum("quantity")
            )["quantity"]
            or 0
        )

    def clean(self):
        if self.total_quantity is not None and self.total_quantity < self.unavailable_quantity:
            raise ValidationError(
                {"total_quantity": "Total stock cannot be below recorded unavailable stock."}
            )


class EquipmentUnavailability(TimeStampedModel):
    equipment_type = models.ForeignKey(
        EquipmentType, on_delete=models.PROTECT, related_name="unavailability_records"
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    cause = models.CharField(max_length=20, choices=UnavailabilityCause.choices)
    reason = models.TextField()
    expected_return_at = models.DateTimeField(null=True, blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    restored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="equipment_unavailable_positive_quantity"
            ),
            models.CheckConstraint(
                condition=Q(cause__in=UnavailabilityCause.values),
                name="equipment_unavailable_valid_cause",
            ),
            models.CheckConstraint(
                condition=~Q(reason__regex=r"^\s*$"), name="equipment_unavailable_has_reason"
            ),
            models.CheckConstraint(
                condition=(
                    Q(restored_at__isnull=True, restored_by__isnull=True)
                    | Q(restored_at__isnull=False, restored_by__isnull=False)
                ),
                name="equipment_restoration_has_actor_time",
            ),
        ]

    def __str__(self):
        return f"{self.equipment_type_id}: {self.quantity} {self.get_cause_display()}"

    def clean(self):
        if self.expected_return_at and timezone.is_naive(self.expected_return_at):
            raise ValidationError({"expected_return_at": "Use a timezone-aware return estimate."})
        if self.equipment_type_id and self.quantity is not None and self.restored_at is None:
            item = EquipmentType.objects.filter(pk=self.equipment_type_id).first()
            if item is None:
                return  # ForeignKey validation supplies the missing-ID error.
            other = (
                item.unavailability_records.filter(restored_at__isnull=True)
                .exclude(pk=self.pk)
                .aggregate(quantity=Sum("quantity"))["quantity"]
                or 0
            )
            if other + self.quantity > item.total_quantity:
                raise ValidationError(
                    {"quantity": "Unavailable quantities cannot exceed total stock."}
                )


class EquipmentPlan(TimeStampedModel):
    """Equipment-only revision, independent of the later global Safety version."""

    event = models.OneToOneField(
        "events.EventRequest", on_delete=models.PROTECT, related_name="equipment_plan"
    )
    revision = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Event {self.event_id}: equipment revision {self.revision}"


class EquipmentRequest(TimeStampedModel):
    plan = models.ForeignKey(EquipmentPlan, on_delete=models.PROTECT, related_name="requests")
    equipment_type = models.ForeignKey(
        EquipmentType, on_delete=models.PROTECT, related_name="requests"
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    technical_requirements = models.TextField(blank=True)
    status = models.CharField(
        max_length=12,
        choices=EquipmentRequestStatus.choices,
        default=EquipmentRequestStatus.REQUESTED,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["requested_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="equipment_request_positive_quantity"
            ),
            models.CheckConstraint(
                condition=Q(status__in=EquipmentRequestStatus.values),
                name="equipment_request_valid_status",
            ),
            models.UniqueConstraint(
                fields=["plan", "equipment_type"],
                condition=~Q(status=EquipmentRequestStatus.WITHDRAWN),
                name="unique_active_equipment_request_type",
            ),
        ]

    def __str__(self):
        return f"Plan {self.plan_id}: type {self.equipment_type_id}, quantity {self.quantity}"


class ReservationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=ReservationStatus.ACTIVE).exclude(
            request__plan__event__status=EventStatus.CANCELLED
        )

    def overlapping(self, starts_at, ends_at):
        from apps.equipment.contracts import validate_period

        validate_period(starts_at, ends_at)
        return self.filter(starts_at__lt=ends_at, ends_at__gt=starts_at)


class EquipmentReservation(TimeStampedModel):
    request = models.ForeignKey(
        EquipmentRequest, on_delete=models.PROTECT, related_name="reservations"
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=10, choices=ReservationStatus.choices, default=ReservationStatus.ACTIVE
    )
    reserved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reserved_at = models.DateTimeField(auto_now_add=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.TextField(blank=True)

    objects = ReservationQuerySet.as_manager()

    class Meta:
        ordering = ["starts_at", "pk"]
        indexes = [
            models.Index(fields=["status", "starts_at", "ends_at"], name="equipment_active_period")
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="equipment_reservation_positive_qty"
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="equipment_reservation_positive_period",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=ReservationStatus.ACTIVE,
                        released_by__isnull=True,
                        released_at__isnull=True,
                        release_reason="",
                    )
                    | (
                        Q(
                            status=ReservationStatus.RELEASED,
                            released_by__isnull=False,
                            released_at__isnull=False,
                        )
                        & ~Q(release_reason__regex=r"^\s*$")
                    )
                ),
                name="equipment_reservation_release_metadata",
            ),
            models.UniqueConstraint(
                fields=["request"],
                condition=Q(status=ReservationStatus.ACTIVE),
                name="unique_active_equipment_reservation",
            ),
        ]

    def __str__(self):
        return f"Request {self.request_id}: {self.quantity} [{self.status}]"

    def clean(self):
        from apps.equipment.contracts import validate_period

        validate_period(self.starts_at, self.ends_at)
        request = EquipmentRequest.objects.filter(pk=self.request_id).first()
        if request and self.quantity is not None and self.quantity > request.quantity:
            raise ValidationError({"quantity": "Reserved quantity cannot exceed the request."})


class TechnicalApproval(TimeStampedModel):
    plan = models.ForeignKey(
        EquipmentPlan, on_delete=models.PROTECT, related_name="technical_approvals"
    )
    plan_revision = models.PositiveIntegerField()
    no_equipment_required = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=12,
        choices=TechnicalApprovalStatus.choices,
        default=TechnicalApprovalStatus.APPROVED,
    )
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-approved_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan"],
                condition=Q(status=TechnicalApprovalStatus.APPROVED),
                name="unique_current_technical_approval",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=TechnicalApprovalStatus.APPROVED, superseded_at__isnull=True)
                    | Q(status=TechnicalApprovalStatus.SUPERSEDED, superseded_at__isnull=False)
                ),
                name="equipment_approval_superseded_time",
            ),
        ]

    def __str__(self):
        return f"Plan {self.plan_id}: technical approval at revision {self.plan_revision}"

    def clean(self):
        plan = EquipmentPlan.objects.filter(pk=self.plan_id).first()
        if plan and self.status == TechnicalApprovalStatus.APPROVED:
            if self.plan_revision != plan.revision:
                raise ValidationError(
                    {"plan_revision": "Approval must use the current equipment revision."}
                )
            if (
                self.no_equipment_required
                and plan.requests.exclude(status=EquipmentRequestStatus.WITHDRAWN).exists()
            ):
                raise ValidationError(
                    {"no_equipment_required": "This plan still has equipment requests."}
                )
            if (
                not self.no_equipment_required
                and not plan.requests.exclude(status=EquipmentRequestStatus.WITHDRAWN).exists()
            ):
                raise ValidationError(
                    {"no_equipment_required": "Explicitly acknowledge a plan needing no equipment."}
                )


class EquipmentHistory(models.Model):
    plan = models.ForeignKey(EquipmentPlan, on_delete=models.PROTECT, related_name="history")
    request = models.ForeignKey(
        EquipmentRequest, null=True, blank=True, on_delete=models.PROTECT, related_name="history"
    )
    reservation = models.ForeignKey(
        EquipmentReservation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="history",
    )
    action = models.CharField(max_length=12, choices=EquipmentHistoryAction.choices)
    plan_revision = models.PositiveIntegerField()
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=EquipmentHistoryAction.values),
                name="equipment_history_valid_action",
            )
        ]

    def __str__(self):
        return f"Plan {self.plan_id}: {self.get_action_display()} at {self.created_at}"

    def clean(self):
        if not isinstance(self.before, dict) or not isinstance(self.after, dict):
            raise ValidationError("History snapshots must be JSON objects.")
        request = EquipmentRequest.objects.filter(pk=self.request_id).first()
        reservation = (
            EquipmentReservation.objects.select_related("request")
            .filter(pk=self.reservation_id)
            .first()
        )
        if request and request.plan_id != self.plan_id:
            raise ValidationError(
                {"request": "History request must belong to this equipment plan."}
            )
        if reservation and (
            reservation.request.plan_id != self.plan_id
            or (self.request_id and reservation.request_id != self.request_id)
        ):
            raise ValidationError(
                {"reservation": "History reservation must match this plan and request."}
            )

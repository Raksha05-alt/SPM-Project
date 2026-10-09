"""EP-15 to EP-17 - equipment types, requests from coordinators and reservations."""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class EquipmentType(TimeStampedModel):
    """One kind of equipment ConnectSphere lends out, with how many units it owns.

    Maintained by Technical Support Staff through the Django admin.
    """

    name = models.CharField(max_length=200, unique=True)
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    total_quantity = models.PositiveIntegerField(default=0)
    # SCRUM-12 AC4 / SCRUM-76 AC2 - units that are damaged or under maintenance.
    out_of_service_quantity = models.PositiveIntegerField(default=0)
    out_of_service_reason = models.CharField(max_length=300, blank=True)
    expected_return = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def in_service_quantity(self) -> int:
        return max(self.total_quantity - self.out_of_service_quantity, 0)


class EquipmentRequestStatus(models.TextChoices):
    REQUESTED = "REQUESTED", "Requested"
    RESERVED = "RESERVED", "Reserved"
    UNAVAILABLE = "UNAVAILABLE", "Unavailable"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class EquipmentRequest(TimeStampedModel):
    """SCRUM-74 - equipment an event needs, recorded by its coordinator."""

    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="equipment_requests"
    )
    equipment_type = models.ForeignKey(
        EquipmentType, on_delete=models.PROTECT, related_name="requests"
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    technical_requirements = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=EquipmentRequestStatus.choices,
        default=EquipmentRequestStatus.REQUESTED,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    # SCRUM-58 AC3 - Technical Support Staff record that it cannot be provided.
    unavailable_reason = models.TextField(blank=True)

    # SCRUM-59 / SCRUM-80 - an arrangement staff must look at again.
    review_required = models.BooleanField(default=False)
    review_reason = models.TextField(blank=True)
    review_flagged_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_outcome = models.TextField(blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.equipment_type} for event {self.event_id}"

    def active_reservations(self):
        return self.reservations.filter(released_at__isnull=True)

    @property
    def reserved_quantity(self) -> int:
        return sum(r.quantity for r in self.active_reservations())


class EquipmentRequestChange(models.Model):
    """SCRUM-75 AC4 - what changed on a request, who changed it and when."""

    request = models.ForeignKey(EquipmentRequest, on_delete=models.CASCADE, related_name="changes")
    description = models.TextField()
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["changed_at", "pk"]

    def __str__(self) -> str:
        return self.description


class EquipmentReservation(models.Model):
    """SCRUM-16 - units held for an event's period; SCRUM-77 - and their release."""

    request = models.ForeignKey(
        EquipmentRequest, on_delete=models.CASCADE, related_name="reservations"
    )
    event = models.ForeignKey(
        "events.EventRequest", on_delete=models.CASCADE, related_name="equipment_reservations"
    )
    equipment_type = models.ForeignKey(
        EquipmentType, on_delete=models.PROTECT, related_name="reservations"
    )
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    start = models.DateTimeField()
    end = models.DateTimeField()
    reserved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    reserved_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    release_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["start", "pk"]
        indexes = [models.Index(fields=["equipment_type", "start", "end"])]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.equipment_type} for event {self.event_id}"

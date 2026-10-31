"""Repeatable catalogue examples, without fake requests or resource approval."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.equipment.inventory import save_unavailability
from apps.equipment.models import EquipmentType, EquipmentUnavailability, UnavailabilityCause


class Command(BaseCommand):
    help = "Seed equipment types and unavailable-stock examples; preserve existing stock."

    @transaction.atomic
    def handle(self, *args, **options):
        reporter = (
            User.objects.filter(role=Role.TECHNICAL_SUPPORT, is_active=True).order_by("pk").first()
        )
        if reporter is None:
            raise CommandError(
                "Run seed_demo_data first, or create an active Technical Support account."
            )
        samples = [
            (
                "PROJECTOR",
                "Projector",
                10,
                2,
                UnavailabilityCause.DAMAGED,
                "Lens damage; awaiting repair",
            ),
            (
                "MICROPHONE",
                "Wireless microphone",
                12,
                1,
                UnavailabilityCause.MAINTENANCE,
                "Battery and transmitter maintenance",
            ),
            ("SPEAKER", "Portable speaker", 4, 0, None, ""),
        ]
        for code, name, total, unavailable, cause, reason in samples:
            item, created = EquipmentType.objects.get_or_create(
                code=code, defaults={"name": name, "total_quantity": total}
            )
            # Existing stock and restored records belong to staff, not the seed.
            if created and unavailable:
                save_unavailability(
                    EquipmentUnavailability(
                        equipment_type=item,
                        quantity=unavailable,
                        cause=cause,
                        reason=reason,
                        reported_by=reporter,
                        expected_return_at=timezone.now() + timezone.timedelta(days=14),
                    )
                )
        self.stdout.write(
            self.style.SUCCESS("Equipment catalogue seeded; existing quantities preserved.")
        )

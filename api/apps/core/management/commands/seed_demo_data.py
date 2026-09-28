"""Repeatable demo data: one user per role plus a few event requests.

Run with:  python manage.py seed_demo_data
Safe to run more than once; it updates rather than duplicating.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import ClientOrganisation, Role, User
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest, EventStatusHistory

DEMO_PASSWORD = "connectsphere-demo"

PEOPLE = [
    ("organiser@acme.example", Role.EVENT_ORGANISER, "Ada", "Organiser", "Acme Pte Ltd"),
    ("organiser@globex.example", Role.EVENT_ORGANISER, "Otto", "Other", "Globex LLP"),
    ("coordinator@connectsphere.example", Role.EVENT_COORDINATOR, "Cora", "Coordinator", None),
    ("venue@connectsphere.example", Role.VENUE_STAFF, "Vera", "Venue", None),
    ("tech@connectsphere.example", Role.TECHNICAL_SUPPORT, "Tariq", "Tech", None),
    ("attendee@example.com", Role.ATTENDEE, "Andy", "Attendee", None),
]


class Command(BaseCommand):
    help = "Create demo organisations, one user per role, and sample event requests."

    def handle(self, *args, **options):
        orgs = {}
        for name in ("Acme Pte Ltd", "Globex LLP"):
            org, _ = ClientOrganisation.objects.get_or_create(
                name=name, defaults={"contact_email": f"ops@{name.split()[0].lower()}.example"}
            )
            orgs[name] = org

        users = {}
        for email, role, first, last, org_name in PEOPLE:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "username": email,
                    "role": role,
                    "first_name": first,
                    "last_name": last,
                    "organisation": orgs.get(org_name),
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
            users[email] = user

        organiser = users["organiser@acme.example"]
        start = timezone.now() + timezone.timedelta(days=45)

        samples = [
            ("Regional Partner Conference", EventStatus.SUBMITTED, 180),
            ("Q4 Engineering Workshop", EventStatus.SUBMITTED, 40),
            ("Product Launch Rehearsal", EventStatus.DRAFT, 25),
        ]
        for offset, (name, status, attendance) in enumerate(samples):
            event, created = EventRequest.objects.get_or_create(
                name=name,
                organisation=organiser.organisation,
                defaults={
                    "created_by": organiser,
                    "purpose": "Demo data seeded for sprint 1",
                    "preferred_start": start + timezone.timedelta(days=offset),
                    "preferred_end": start + timezone.timedelta(days=offset, hours=6),
                    "expected_attendance": attendance,
                    "status": status,
                    "submitted_at": (
                        timezone.now() - timezone.timedelta(days=3 - offset)
                        if status != EventStatus.DRAFT
                        else None
                    ),
                    "status_changed_at": timezone.now(),
                },
            )
            if created and status != EventStatus.DRAFT:
                EventStatusHistory.objects.create(
                    event=event,
                    from_status=EventStatus.DRAFT,
                    to_status=status,
                    changed_by=organiser,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(orgs)} organisations, {len(users)} users and "
                f"{EventRequest.objects.count()} event requests. "
                f"All demo accounts use the password: {DEMO_PASSWORD}"
            )
        )

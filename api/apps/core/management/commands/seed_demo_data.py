"""Repeatable demo data, including two Leads and two coordinators.

Run with:  python manage.py seed_demo_data
Safe to run more than once; it updates rather than duplicating.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import ClientOrganisation, Role, User
from apps.core.statuses import EventStatus
from apps.events.models import EventRequest, EventStatusHistory
from apps.venues.models import Venue

DEMO_PASSWORD = "connectsphere-demo"

PEOPLE = [
    ("organiser@acme.example", Role.EVENT_ORGANISER, "Ada", "Organiser", "Acme Pte Ltd"),
    ("organiser@globex.example", Role.EVENT_ORGANISER, "Otto", "Other", "Globex LLP"),
    ("coordinator@connectsphere.example", Role.EVENT_COORDINATOR, "Cora", "Coordinator", None),
    ("coordinator2@connectsphere.example", Role.EVENT_COORDINATOR, "Casey", "Coordinator", None),
    ("lead@connectsphere.example", Role.EVENT_COORDINATOR_LEAD, "Lee", "Lead", None),
    ("lead2@connectsphere.example", Role.EVENT_COORDINATOR_LEAD, "Lane", "Lead", None),
    ("venue@connectsphere.example", Role.VENUE_STAFF, "Vera", "Venue", None),
    ("tech@connectsphere.example", Role.TECHNICAL_SUPPORT, "Tariq", "Tech", None),
    ("attendee@example.com", Role.ATTENDEE, "Andy", "Attendee", None),
    ("safety@connectsphere.example", Role.SAFETY_OFFICER, "Sam", "Safety", None),
]


class Command(BaseCommand):
    help = "Create demo organisations, role accounts, Leads, and sample event requests."

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
                    "assignment_requires_attention": status != EventStatus.DRAFT,
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

        venues = self._seed_venues(users["venue@connectsphere.example"])
        call_command("seed_equipment_catalogue", stdout=self.stdout)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(orgs)} organisations, {len(users)} users, "
                f"{EventRequest.objects.count()} event requests and {len(venues)} venues. "
                f"All demo accounts use the password: {DEMO_PASSWORD}"
            )
        )

    def _seed_venues(self, staff) -> dict[str, Venue]:
        """SCRUM-65 - a small catalogue for Venue Staff to maintain."""
        rows = [
            {
                "name": "Harbour Hall",
                "location": "Level 2, Marina Wing",
                "capacity": 200,
                "facilities": ["Projector", "Stage", "Hearing loop"],
                "layouts": ["THEATRE", "BANQUET"],
                "wheelchair_access": True,
                "accessibility_notes": "Step-free entrance and accessible toilets on level 2.",
                "emergency_access": "Two fire exits to the Marina Wing stairwell; assembly "
                "point at the waterfront promenade.",
                "known_restrictions": "No open flames or pyrotechnics. Stage load limit 500 kg.",
            },
            {
                "name": "Skyline Room",
                "location": "Level 30, Tower One",
                "capacity": 60,
                "facilities": ["Video conferencing", "Whiteboard"],
                "layouts": ["BOARDROOM", "CLASSROOM"],
                "wheelchair_access": True,
            },
            {
                "name": "Garden Pavilion",
                "location": "Ground floor, East Courtyard",
                "capacity": 120,
                "facilities": ["Outdoor PA"],
                "layouts": ["EXHIBITION", "BANQUET"],
                "wheelchair_access": False,
                "accessibility_notes": "Gravel path; ramp access via the east gate only.",
            },
            # SCRUM-9 AC3 - a venue still missing details, to show how gaps are named.
            {"name": "Studio Annex", "capacity": 25, "location": "Basement, Tower One"},
        ]
        venues = {}
        for row in rows:
            venue, _ = Venue.objects.get_or_create(
                name=row["name"],
                defaults={
                    "opens_at": "08:00" if row.get("layouts") else None,
                    "closes_at": "22:00" if row.get("layouts") else None,
                    **row,
                    "created_by": staff,
                    "updated_by": staff,
                },
            )
            venues[venue.name] = venue
        return venues

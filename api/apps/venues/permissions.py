from apps.accounts.models import INTERNAL_ROLES, Role

# Venue records are internal planning information: clients and attendees never
# reach them. Only Venue Staff may create or change them (SCRUM-65 AC4).
VENUE_READERS = INTERNAL_ROLES
VENUE_EDITORS = frozenset({Role.VENUE_STAFF})

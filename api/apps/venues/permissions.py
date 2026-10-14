from apps.accounts.models import INTERNAL_ROLES as ALL_INTERNAL_ROLES
from apps.accounts.models import Role

# SCRUM-9 / SCRUM-17 / SCRUM-64 - venue information is internal planning
# information. Clients and attendees never reach it. Every internal role reads it,
# including the Week 7 Event Coordinator Lead and Safety Officer; only Venue Staff
# change it.
INTERNAL_ROLES = ALL_INTERNAL_ROLES
VENUE_STAFF_ONLY = frozenset({Role.VENUE_STAFF})
COORDINATOR_ONLY = frozenset({Role.EVENT_COORDINATOR})

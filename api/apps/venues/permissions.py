from apps.accounts.models import Role

# SCRUM-9 / SCRUM-17 / SCRUM-64 - venue information is internal planning
# information. Clients and attendees never reach it.
INTERNAL_ROLES = frozenset({Role.EVENT_COORDINATOR, Role.VENUE_STAFF, Role.TECHNICAL_SUPPORT})
VENUE_STAFF_ONLY = frozenset({Role.VENUE_STAFF})
COORDINATOR_ONLY = frozenset({Role.EVENT_COORDINATOR})

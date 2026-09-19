"""Edge cases and defensive branches that the acceptance-criterion tests do not reach.

Kept in a separate file so that the per-story test files stay a clean one-to-one
mapping onto the backlog.
"""

import pytest

from apps.accounts.models import Role
from apps.core.statuses import EventStatus
from conftest import make_event

EVENTS = "/api/events/"


# --- coordinator object-level rules (apps/events/permissions.py) ---------------


@pytest.mark.django_db
def test_a_coordinator_can_open_a_submitted_request(signed_in_coordinator, submitted_event):
    response = signed_in_coordinator.get(f"{EVENTS}{submitted_event.pk}/")

    assert response.status_code == 200
    assert response.data["status"] == EventStatus.SUBMITTED


@pytest.mark.django_db
def test_a_coordinator_cannot_open_a_clients_draft(signed_in_coordinator, complete_draft):
    response = signed_in_coordinator.get(f"{EVENTS}{complete_draft.pk}/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_coordinator_cannot_edit_a_request_in_this_release(
    signed_in_coordinator, submitted_event
):
    response = signed_in_coordinator.patch(
        f"{EVENTS}{submitted_event.pk}/", {"name": "Renamed by ConnectSphere"}, format="json"
    )

    assert response.status_code == 403
    submitted_event.refresh_from_db()
    assert submitted_event.name == "Regional Partner Conference"


@pytest.mark.django_db
def test_a_coordinator_sees_submitted_requests_in_the_main_list(
    signed_in_coordinator, complete_draft, submitted_event
):
    response = signed_in_coordinator.get(EVENTS)

    ids = [row["id"] for row in response.data]
    assert submitted_event.pk in ids
    assert complete_draft.pk not in ids


# --- missing objects and unlinked accounts (apps/events/views.py) -------------


@pytest.mark.django_db
def test_an_unknown_event_id_is_a_404(signed_in_organiser):
    assert signed_in_organiser.get(f"{EVENTS}999999/").status_code == 404


@pytest.mark.django_db
def test_an_organiser_with_no_client_organisation_cannot_create_a_request(api, db):
    from apps.accounts.models import User

    orphan = User.objects.create_user(
        username="orphan@nowhere.example",
        email="orphan@nowhere.example",
        password="Sprint1-Test-Passw0rd",
        role=Role.EVENT_ORGANISER,
    )
    api.force_authenticate(orphan)

    response = api.post(EVENTS, {"name": "Nowhere conference"}, format="json")

    assert response.status_code == 403
    assert "client organisation" in str(response.data)


@pytest.mark.django_db
def test_a_role_with_no_event_access_gets_an_empty_queryset(api, venue_staff, submitted_event):
    """HasAnyRole refuses first, so the empty queryset is a second line of defence."""
    from apps.events.views import EventRequestViewSet

    view = EventRequestViewSet()
    view.request = type("R", (), {"user": venue_staff})()

    assert view.get_queryset().count() == 0


# --- serializer null branches -------------------------------------------------


@pytest.mark.django_db
def test_an_unassigned_request_reports_no_coordinator(
    signed_in_coordinator, submitted_event, coordinator
):
    unassigned = signed_in_coordinator.get(f"{EVENTS}{submitted_event.pk}/")
    assert unassigned.data["coordinator_name"] is None

    submitted_event.coordinator = coordinator
    submitted_event.save(update_fields=["coordinator"])

    assigned = signed_in_coordinator.get(f"{EVENTS}{submitted_event.pk}/")
    assert assigned.data["coordinator_name"] == "Cora Coordinator"
    queue_row = signed_in_coordinator.get(f"{EVENTS}queue/").data[0]
    assert queue_row["coordinator_name"] == "Cora Coordinator"


@pytest.mark.django_db
def test_a_user_without_a_name_falls_back_to_their_email(signed_in_organiser, organiser):
    organiser.first_name = ""
    organiser.last_name = ""
    organiser.save(update_fields=["first_name", "last_name"])
    event = make_event(organiser)

    response = signed_in_organiser.get(f"{EVENTS}{event.pk}/")

    assert response.data["created_by_name"] == organiser.email


# --- readable string representations -----------------------------------------


@pytest.mark.django_db
def test_models_have_readable_string_representations(organiser, complete_draft, acme):
    from apps.core.audit import record_denied

    assert str(acme) == "Acme Pte Ltd"
    assert str(organiser) == "Ada Organiser <organiser@acme.example>"
    assert "Regional Partner Conference" in str(complete_draft)
    assert "Draft" in str(complete_draft)

    untitled = make_event(organiser, complete=False)
    assert "(untitled draft)" in str(untitled)

    entry = record_denied(organiser, "GET /api/events/1/", obj=complete_draft, detail="nope")
    assert "refused" in str(entry)


@pytest.mark.django_db
def test_status_history_describes_the_move(signed_in_organiser, complete_draft):
    signed_in_organiser.post(f"{EVENTS}{complete_draft.pk}/submit/")

    history = complete_draft.status_history.get()

    assert "DRAFT -> SUBMITTED" in str(history)


@pytest.mark.django_db
def test_the_csrf_endpoint_sets_the_cookie_for_the_spa(api):
    response = api.get("/api/auth/csrf/")

    assert response.status_code == 200
    assert "csrftoken" in response.cookies


@pytest.mark.django_db
def test_an_internal_user_is_flagged_as_internal(coordinator, venue_staff, attendee, organiser):
    assert coordinator.is_internal
    assert venue_staff.is_internal
    assert not attendee.is_internal
    assert not organiser.is_internal


# --- defence-in-depth branches, tested directly -------------------------------
# These checks are unreachable over HTTP because an earlier permission fires
# first. They are tested at unit level so that the second line of defence is
# still verified, and so that sprint 2 cannot quietly remove it.


@pytest.mark.django_db
def test_role_permission_refuses_an_anonymous_user(rf):
    from django.contrib.auth.models import AnonymousUser

    from apps.core.permissions import HasAnyRole

    request = rf.get("/api/events/")
    request.user = AnonymousUser()
    view = type("V", (), {"allowed_roles": frozenset({Role.EVENT_ORGANISER})})()

    assert HasAnyRole().has_permission(request, view) is False


@pytest.mark.django_db
def test_role_permission_allows_a_view_that_declares_no_roles(rf, attendee):
    from apps.core.permissions import HasAnyRole

    request = rf.get("/api/health/")
    request.user = attendee

    assert HasAnyRole().has_permission(request, type("V", (), {})()) is True


@pytest.mark.django_db
def test_object_permission_refuses_a_role_with_no_event_access(rf, venue_staff, submitted_event):
    from apps.core.models import AuditLog
    from apps.events.permissions import CanAccessEventRequest

    request = rf.get(f"/api/events/{submitted_event.pk}/")
    request.user = venue_staff

    allowed = CanAccessEventRequest().has_object_permission(request, None, submitted_event)

    assert allowed is False
    assert AuditLog.objects.filter(allowed=False, actor=venue_staff).exists()


@pytest.mark.django_db
def test_perform_destroy_refuses_anything_that_is_not_a_draft(rf, organiser, submitted_event):
    from rest_framework.exceptions import PermissionDenied

    from apps.events.models import EventRequest
    from apps.events.views import EventRequestViewSet

    request = rf.delete(f"/api/events/{submitted_event.pk}/")
    request.user = organiser
    view = EventRequestViewSet()
    view.request = request

    with pytest.raises(PermissionDenied):
        view.perform_destroy(submitted_event)

    assert EventRequest.objects.filter(pk=submitted_event.pk).exists()

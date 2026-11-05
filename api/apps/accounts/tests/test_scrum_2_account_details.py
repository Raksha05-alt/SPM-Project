"""SCRUM-2 - maintain my own account details.

Users sign in through the real /api/auth/login/ session, so the session
behaviour after an email change is exercised, not assumed.
"""

from unittest import mock

import pytest

from apps.accounts.models import Role, User
from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.notifications.models import Notification, NotificationKind
from conftest import _make_user, make_event

pytestmark = pytest.mark.django_db
ME = "/api/auth/me/"
LOGIN = "/api/auth/login/"


def sign_in(api, user, password, email=None):
    response = api.post(LOGIN, {"email": email or user.email, "password": password}, format="json")
    assert response.status_code == 200, response.data
    return response


def patch(api, data):
    return api.patch(ME, data, format="json")


# --------------------------------------------------------------------------
# AC1 - my name, organisation, role and contact details
# --------------------------------------------------------------------------


def test_ac1a_my_account_shows_name_organisation_role_and_email(api, organiser, password):
    sign_in(api, organiser, password)

    data = api.get(ME).data

    assert (data["first_name"], data["last_name"]) == ("Ada", "Organiser")
    assert data["organisation_name"] == "Acme Pte Ltd"
    assert (data["role"], data["role_label"]) == (Role.EVENT_ORGANISER, "Event Organiser")
    assert data["email"] == "organiser@acme.example"


def test_ac1b_staff_without_an_organisation_see_none(api, coordinator, password):
    sign_in(api, coordinator, password)

    data = api.get(ME).data

    assert data["organisation_name"] is None
    assert data["role_label"] == "Event Coordinator"


def test_ac1c_signed_out_users_cannot_read_or_change_an_account(api, organiser):
    assert api.get(ME).status_code in (401, 403)
    assert patch(api, {"first_name": "X"}).status_code in (401, 403)
    organiser.refresh_from_db()
    assert organiser.first_name == "Ada"


# --------------------------------------------------------------------------
# AC2 - new details are stored and used afterwards
# --------------------------------------------------------------------------


def test_ac2a_changed_details_are_stored_and_returned(api, organiser, password):
    sign_in(api, organiser, password)

    response = patch(
        api, {"first_name": " Adaline ", "last_name": "Org", "email": "ada@Acme.Example"}
    )

    assert response.status_code == 200, response.data
    assert response.data["changed_fields"] == ["first_name", "last_name", "email"]
    organiser.refresh_from_db()
    assert (organiser.first_name, organiser.last_name) == ("Adaline", "Org")
    # The domain is normalised to lower case, as Django stores new accounts.
    assert organiser.email == "ada@acme.example"
    assert api.get(ME).data["email"] == "ada@acme.example"
    assert AuditLog.objects.filter(
        actor=organiser, allowed=True, detail="Changed: first_name, last_name, email"
    ).exists()


def test_ac2b_the_session_continues_and_the_next_sign_in_uses_the_new_email(
    api, organiser, password
):
    sign_in(api, organiser, password)
    patch(api, {"email": "ada.new@acme.example"})

    # Still signed in after the change.
    assert api.get(ME).status_code == 200

    api.post("/api/auth/logout/")
    old = api.post(LOGIN, {"email": "organiser@acme.example", "password": password}, format="json")
    assert old.status_code == 401
    sign_in(api, organiser, password, email="ada.new@acme.example")


def test_ac2c_later_notices_quote_the_new_contact_details(
    api, coordinator, lead, organiser, password
):
    """A coordinator's new email reaches the client in the next assignment notice
    and on the event, while notices sent earlier keep their original text."""
    event = make_event(organiser, status=EventStatus.SUBMITTED)
    api.force_authenticate(lead)
    api.post(
        f"/api/events/{event.pk}/assign-coordinator/",
        {"coordinator_id": coordinator.pk, "expected_revision": 0},
        format="json",
    )
    before = Notification.objects.get(recipient=organiser, kind=NotificationKind.ASSIGNMENT)

    api.force_authenticate(None)
    sign_in(api, coordinator, password)
    assert patch(api, {"email": "cora.new@connectsphere.example"}).status_code == 200

    second = make_event(organiser, status=EventStatus.SUBMITTED)
    api.force_authenticate(lead)
    api.post(
        f"/api/events/{second.pk}/assign-coordinator/",
        {"coordinator_id": coordinator.pk, "expected_revision": 0},
        format="json",
    )
    after = Notification.objects.get(
        recipient=organiser, kind=NotificationKind.ASSIGNMENT, event=second
    )
    assert "cora.new@connectsphere.example" in after.message
    before.refresh_from_db()
    assert "coordinator@connectsphere.example" in before.message
    api.force_authenticate(organiser)
    assert api.get(f"/api/events/{second.pk}/").data["coordinator_email"] == (
        "cora.new@connectsphere.example"
    )


def test_ac2d_in_app_notices_keep_reaching_the_account_after_an_email_change(
    api, coordinator, lead, organiser, password
):
    sign_in(api, coordinator, password)
    patch(api, {"email": "cora.new@connectsphere.example"})
    event = make_event(organiser, status=EventStatus.SUBMITTED)
    api.force_authenticate(lead)
    api.post(
        f"/api/events/{event.pk}/assign-coordinator/",
        {"coordinator_id": coordinator.pk, "expected_revision": 0},
        format="json",
    )

    api.force_authenticate(None)
    sign_in(api, coordinator, password, email="cora.new@connectsphere.example")
    assert [n["kind"] for n in api.get("/api/notifications/").data] == [NotificationKind.ASSIGNMENT]


def test_ac2e_a_save_that_changes_nothing_records_nothing(api, organiser, password):
    sign_in(api, organiser, password)

    response = patch(api, {"first_name": "Ada", "email": "organiser@acme.example"})

    assert response.status_code == 200
    assert response.data["changed_fields"] == []
    assert not AuditLog.objects.filter(action="PATCH /api/auth/me/").exists()


# --------------------------------------------------------------------------
# AC3 - I cannot change my role (or anything else that grants access)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attempt",
    [
        {"role": Role.EVENT_COORDINATOR_LEAD},
        {"organisation": None},
        {"is_staff": True},
        {"is_superuser": True},
        {"is_active": False},
        {"username": "someone-else"},
        {"coordinator_available": False},
        {"password": "new-password-123"},
        {"id": 999},
    ],
    ids=lambda a: next(iter(a)),
)
def test_ac3a_changing_role_or_privileges_is_refused_and_audited(api, organiser, password, attempt):
    sign_in(api, organiser, password)

    response = patch(api, {"first_name": "Changed", **attempt})

    assert response.status_code == 403
    assert response.data["refused_fields"] == sorted(attempt)
    organiser.refresh_from_db()
    # Nothing is saved, not even the allowed field sent alongside.
    assert organiser.first_name == "Ada"
    assert organiser.role == Role.EVENT_ORGANISER
    assert organiser.organisation.name == "Acme Pte Ltd"
    assert not organiser.is_staff and not organiser.is_superuser and organiser.is_active
    assert organiser.check_password(password)
    assert AuditLog.objects.filter(
        actor=organiser, allowed=False, detail__startswith="own account: cannot change"
    ).exists()


def test_ac3b_a_refused_role_change_leaves_access_unchanged(api, attendee, password):
    sign_in(api, attendee, password)

    patch(api, {"role": Role.EVENT_COORDINATOR_LEAD})

    assert api.get(ME).data["role"] == Role.ATTENDEE
    assert api.get("/api/events/unassigned/").status_code == 403


def test_ac3c_there_is_no_way_to_edit_another_users_account(api, organiser, coordinator, password):
    sign_in(api, organiser, password)

    response = patch(api, {"first_name": "Mallory"})

    assert response.status_code == 200
    coordinator.refresh_from_db()
    assert coordinator.first_name == "Cora"
    # The endpoint only ever means "me": there is no per-user account route.
    assert api.patch(f"/api/auth/users/{coordinator.pk}/", {"first_name": "X"}).status_code == 404
    assert api.put(ME, {"first_name": "X"}, format="json").status_code == 405


# --------------------------------------------------------------------------
# AC4 - an empty required field blocks the save and is named
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "field", "message"),
    [
        ({"email": ""}, "email", "Email address is required."),
        ({"email": "   "}, "email", "Email address is required."),
        ({"email": None}, "email", "Email address is required."),
        ({"first_name": ""}, "first_name", "First name is required."),
    ],
    ids=["blank-email", "spaces-email", "null-email", "blank-first-name"],
)
def test_ac4a_an_empty_required_field_is_named_and_nothing_is_saved(
    api, organiser, password, data, field, message
):
    sign_in(api, organiser, password)

    response = patch(api, {"last_name": "Saved?", **data})

    assert response.status_code == 400
    assert response.data[field] == [message]
    assert response.data["missing_fields"] == [field]
    organiser.refresh_from_db()
    assert organiser.last_name == "Organiser"


def test_ac4b_every_problem_is_named_at_once(api, organiser, password):
    sign_in(api, organiser, password)

    response = patch(api, {"first_name": "", "email": "not-an-email"})

    assert response.status_code == 400
    assert response.data["first_name"] == ["First name is required."]
    assert response.data["email"] == ["Enter a valid email address."]
    assert response.data["missing_fields"] == ["first_name"]


def test_ac4c_an_email_another_account_uses_is_refused(api, organiser, coordinator, password):
    sign_in(api, organiser, password)

    response = patch(api, {"email": "COORDINATOR@connectsphere.example"})

    assert response.status_code == 400
    assert response.data["email"] == ["Another account already uses this email address."]
    organiser.refresh_from_db()
    assert organiser.email == "organiser@acme.example"


def test_ac4d_last_name_is_optional(api, organiser, password):
    sign_in(api, organiser, password)

    assert patch(api, {"last_name": ""}).status_code == 200
    organiser.refresh_from_db()
    assert organiser.last_name == ""


@pytest.mark.parametrize(
    ("data", "field", "message"),
    [
        ({"first_name": 7}, "first_name", "First name must be text."),
        ({"last_name": "x" * 151}, "last_name", "Last name must be at most 150 characters."),
        ({"email": "a" * 250 + "@x.example"}, "email", "Email address is too long."),
    ],
    ids=["number", "long-name", "long-email"],
)
def test_ac4e_malformed_values_are_refused(api, organiser, password, data, field, message):
    sign_in(api, organiser, password)

    response = patch(api, data)

    assert response.status_code == 400
    assert response.data[field] == [message]


def test_ac4f_a_body_that_is_not_an_object_is_refused(api, organiser, password):
    sign_in(api, organiser, password)

    response = api.patch(ME, ["first_name"], format="json")

    assert response.status_code == 400
    assert response.data["non_field_errors"] == ["Send the details to change."]


def test_ac4g_a_failed_save_leaves_the_account_unchanged(api, organiser, password):
    sign_in(api, organiser, password)

    with (
        mock.patch("apps.accounts.account.record", side_effect=RuntimeError("audit down")),
        pytest.raises(RuntimeError),
    ):
        patch(api, {"first_name": "Lost"})

    organiser.refresh_from_db()
    assert organiser.first_name == "Ada"


def test_ac4h_every_role_can_maintain_their_details(api, password):
    for role in Role.values:
        user = _make_user(f"{role.lower()}@x.example", role)
        api.force_authenticate(user)
        assert patch(api, {"first_name": "Renamed"}).status_code == 200
        assert User.objects.get(pk=user.pk).first_name == "Renamed"

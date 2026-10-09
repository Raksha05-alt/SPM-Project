"""SCRUM-2 (US-01.3) - maintain my own account details."""

import pytest

from apps.accounts.models import Role
from apps.core.models import AuditLog
from apps.notifications.models import Notification

ME = "/api/auth/me/"


@pytest.mark.django_db
def test_ac1_the_account_page_shows_name_organisation_role_and_contact_details(
    signed_in_organiser,
):
    response = signed_in_organiser.get(ME)

    assert response.status_code == 200
    assert response.data["first_name"] == "Ada"
    assert response.data["last_name"] == "Organiser"
    assert response.data["organisation_name"] == "Acme Pte Ltd"
    assert response.data["role_label"] == "Event Organiser"
    assert response.data["email"] == "organiser@acme.example"
    assert response.data["phone"] == ""


@pytest.mark.django_db
def test_ac2_changed_contact_details_are_stored(signed_in_organiser, organiser):
    response = signed_in_organiser.patch(
        ME, {"email": "ada@acme.example", "phone": "+65 6123 4567"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["email"] == "ada@acme.example"
    organiser.refresh_from_db()
    assert organiser.email == "ada@acme.example"
    assert organiser.phone == "+65 6123 4567"
    assert AuditLog.objects.filter(actor=organiser, action="PATCH /api/auth/me/").exists()


@pytest.mark.django_db
def test_ac2_new_contact_details_are_used_in_subsequent_notifications(
    api, coordinator, organiser, complete_draft
):
    api.force_authenticate(coordinator)
    api.patch(ME, {"email": "cora.new@connectsphere.example"}, format="json")

    api.force_authenticate(organiser)
    response = api.post(f"/api/events/{complete_draft.pk}/submit/")

    assert response.status_code == 200
    assert response.data["coordinator_email"] == "cora.new@connectsphere.example"
    notice = Notification.objects.get(recipient=organiser, event=complete_draft)
    assert "cora.new@connectsphere.example" in notice.message


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [("role", Role.EVENT_COORDINATOR), ("organisation", None)])
def test_ac3_changing_my_own_role_or_organisation_is_refused(
    signed_in_organiser, organiser, field, value
):
    response = signed_in_organiser.patch(ME, {field: value, "phone": "999"}, format="json")

    assert response.status_code == 403
    organiser.refresh_from_db()
    assert organiser.role == Role.EVENT_ORGANISER
    assert organiser.organisation is not None
    assert organiser.phone == ""
    assert AuditLog.objects.filter(actor=organiser, allowed=False).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["first_name", "last_name", "email"])
def test_ac4_an_empty_required_field_blocks_the_save_and_is_named(
    signed_in_organiser, organiser, field
):
    response = signed_in_organiser.patch(ME, {field: ""}, format="json")

    assert response.status_code == 400
    assert field in response.data
    organiser.refresh_from_db()
    assert getattr(organiser, field) != ""


@pytest.mark.django_db
def test_an_email_already_used_by_another_account_is_refused(signed_in_organiser, other_organiser):
    response = signed_in_organiser.patch(ME, {"email": other_organiser.email}, format="json")

    assert response.status_code == 400
    assert "email" in response.data


@pytest.mark.django_db
def test_an_invalid_email_is_refused(signed_in_organiser):
    response = signed_in_organiser.patch(ME, {"email": "not-an-email"}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_keeping_my_own_email_is_not_a_clash(signed_in_organiser, organiser):
    response = signed_in_organiser.patch(ME, {"email": organiser.email}, format="json")

    assert response.status_code == 200


@pytest.mark.django_db
def test_signed_out_users_cannot_change_account_details(api):
    response = api.patch(ME, {"phone": "1"}, format="json")

    assert response.status_code == 403

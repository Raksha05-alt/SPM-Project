"""US-01.1 - Sign in and land on my role's view.

One test per acceptance criterion, named after the criterion.
"""

import pytest

from apps.accounts.models import Role

LOGIN = "/api/auth/login/"
ME = "/api/auth/me/"
LOGOUT = "/api/auth/logout/"


@pytest.mark.django_db
def test_ac1_valid_credentials_land_on_the_role_view(api, organiser, password):
    response = api.post(LOGIN, {"email": organiser.email, "password": password}, format="json")

    assert response.status_code == 200
    assert response.data["role"] == Role.EVENT_ORGANISER
    assert response.data["landing_path"] == "/organiser"
    assert response.data["organisation_name"] == "Acme Pte Ltd"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fixture_name", "expected_path"),
    [
        ("coordinator", "/coordinator"),
        ("venue_staff", "/venues"),
        ("attendee", "/events"),
    ],
)
def test_ac1_every_role_has_its_own_landing_path(
    api, request, password, fixture_name, expected_path
):
    user = request.getfixturevalue(fixture_name)

    response = api.post(LOGIN, {"email": user.email, "password": password}, format="json")

    assert response.status_code == 200
    assert response.data["landing_path"] == expected_path


@pytest.mark.django_db
def test_ac2_invalid_credentials_are_refused_without_naming_the_wrong_field(api, organiser):
    response = api.post(
        LOGIN, {"email": organiser.email, "password": "definitely-wrong"}, format="json"
    )

    assert response.status_code == 401
    body = str(response.data).lower()
    assert "password" not in body
    assert "email" not in body
    assert api.get(ME).status_code == 403


@pytest.mark.django_db
def test_ac3_signing_out_ends_the_session(api, organiser, password):
    api.post(LOGIN, {"email": organiser.email, "password": password}, format="json")
    assert api.get(ME).status_code == 200

    assert api.post(LOGOUT).status_code == 204

    assert api.get(ME).status_code == 403


@pytest.mark.django_db
def test_ac4_an_expired_session_is_returned_to_the_sign_in_screen(api, organiser, password):
    api.post(LOGIN, {"email": organiser.email, "password": password}, format="json")
    assert api.get(ME).status_code == 200

    session = api.session
    session.set_expiry(-1)
    session.save()

    assert api.get(ME).status_code == 403

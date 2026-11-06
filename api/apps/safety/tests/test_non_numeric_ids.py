"""Final E2E defect 2: a non-numeric id in the URL is Not Found, never a server error.

``/api/events/abc/`` and ``/api/safety-checks/abc/decide/`` raised ValueError
(500) because both viewsets look the id up themselves.
"""

import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/events/abc/"),
        ("post", "/api/events/abc/submit/"),
        ("post", "/api/events/1abc/approve/"),
        ("get", "/api/events/undefined/"),
    ],
)
def test_event_routes_refuse_non_numeric_ids_with_404(api, coordinator, method, path):
    api.force_authenticate(coordinator)
    assert getattr(api, method)(path, {}, format="json").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/safety-checks/abc/"), ("post", "/api/safety-checks/abc/decide/")],
)
def test_safety_check_routes_refuse_non_numeric_ids_with_404(api, safety_officer, method, path):
    api.force_authenticate(safety_officer)
    assert getattr(api, method)(path, {}, format="json").status_code == 404


def test_numeric_ids_still_route(api, coordinator):
    api.force_authenticate(coordinator)
    assert api.get("/api/events/999999/").status_code == 404
    assert api.get("/api/events/").status_code == 200

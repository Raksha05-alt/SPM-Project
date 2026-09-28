"""The walking skeleton. If this fails, the deployment is broken, not the feature."""

import pytest


@pytest.mark.django_db
def test_health_returns_ok_without_signing_in(api):
    response = api.get("/api/health/")

    assert response.status_code == 200
    assert response.data == {"status": "ok"}

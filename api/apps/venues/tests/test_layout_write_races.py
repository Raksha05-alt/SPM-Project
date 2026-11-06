"""SCRUM-91 real PostgreSQL races after both requests validate.

The barrier pauses the save boundary, not the database. Unique constraints
must reject the losing writer and the API must translate that failure to 400.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connections
from rest_framework.test import APIClient

from apps.venues.layout_views import LayoutTypeSerializer
from apps.venues.models import LayoutType

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("operation", ["create_duplicate_code", "rename_to_duplicate_name"])
def test_scrum91_simultaneous_layout_writers_return_validation_errors_instead_of_500(
    venue_staff, monkeypatch, operation
):
    gate = Barrier(2)
    save = LayoutTypeSerializer.save

    def save_after_both_validate(self, **kwargs):
        gate.wait(timeout=10)
        return save(self, **kwargs)

    monkeypatch.setattr(LayoutTypeSerializer, "save", save_after_both_validate)
    if operation == "rename_to_duplicate_name":
        for code, name in [("RACE_A", "First layout"), ("RACE_B", "Second layout")]:
            LayoutType.objects.create(code=code, name=name)

    def send(index):
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(venue_staff)
            if operation == "create_duplicate_code":
                return api.post(
                    "/api/layouts/",
                    {
                        "code": "RACE_LAYOUT",
                        "name": "Concurrent layout",
                        "description": "",
                    },
                    format="json",
                )
            code = ["RACE_A", "RACE_B"][index]
            return api.patch(f"/api/layouts/{code}/", {"name": "Shared layout name"}, format="json")
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, [0, 1]))
    success = 201 if operation == "create_duplicate_code" else 200
    assert sorted(r.status_code for r in responses) == [success, 400]
    refusal = next(r for r in responses if r.status_code == 400)
    assert "already exists" in str(refusal.data)
    if operation == "create_duplicate_code":
        assert LayoutType.objects.filter(code="RACE_LAYOUT").count() == 1
    else:
        rows = list(LayoutType.objects.filter(code__in=["RACE_A", "RACE_B"]))
        assert len(rows) == 2
        assert sum(r.name == "Shared layout name" for r in rows) == 1
        assert sum(r.name in ["First layout", "Second layout"] for r in rows) == 1

"""US-01.2 AC4 - the audit trail itself: writing it, reading it, and its edges.

The story-level behaviour lives in
``apps/accounts/tests/test_us_01_2_role_based_access.py``. This file covers the
audit machinery directly, including the paths an HTTP request does not reach.
"""

import pytest

from apps.core.audit import ANONYMOUS, record, record_denied
from apps.core.models import AuditLog

AUDIT = "/api/audit/"


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_anonymous_write_without_a_reason_is_labelled_anonymous():
    from django.contrib.auth.models import AnonymousUser

    entry = record_denied(AnonymousUser(), action="GET /api/events/1/")

    assert entry.actor is None
    assert entry.detail == ANONYMOUS


@pytest.mark.django_db
def test_an_explicit_reason_is_kept_for_an_anonymous_write():
    from django.contrib.auth.models import AnonymousUser

    entry = record_denied(AnonymousUser(), action="GET /api/audit/", detail="not signed in")

    assert entry.detail == "not signed in"


@pytest.mark.django_db
def test_an_allowed_action_is_recorded_as_allowed(organiser, complete_draft):
    entry = record(organiser, "POST /api/events/", allowed=True, obj=complete_draft)

    assert entry.allowed is True
    assert entry.object_type == "EventRequest"
    assert entry.object_id == str(complete_draft.pk)


@pytest.mark.django_db
def test_a_failed_write_returns_none_and_is_logged(organiser, monkeypatch, caplog):
    from apps.core import audit

    def unavailable(*args, **kwargs):
        raise RuntimeError("audit table unavailable")

    monkeypatch.setattr(audit.AuditLog.objects, "create", unavailable)

    entry = record_denied(organiser, action="GET /api/events/1/")

    assert entry is None
    assert "Could not write audit row" in caplog.text


@pytest.mark.django_db
def test_a_failed_audit_write_does_not_poison_the_callers_transaction(organiser, monkeypatch):
    """The savepoint means the caller's own work still commits."""
    from django.db import transaction

    from apps.core import audit
    from apps.events.models import EventRequest

    def unavailable(*args, **kwargs):
        raise RuntimeError("audit table unavailable")

    monkeypatch.setattr(audit.AuditLog.objects, "create", unavailable)

    with transaction.atomic():
        record_denied(organiser, action="GET /api/events/1/")
        EventRequest.objects.create(
            organisation=organiser.organisation,
            created_by=organiser,
            name="Survives the failed audit write",
        )

    assert EventRequest.objects.filter(name="Survives the failed audit write").exists()


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_an_anonymous_reader_is_refused(api):
    assert api.get(AUDIT).status_code == 403


@pytest.mark.django_db
def test_rows_are_newest_first(api, coordinator, organiser):
    record_denied(organiser, action="GET /api/events/1/", detail="first")
    record_denied(organiser, action="GET /api/events/2/", detail="second")
    api.force_authenticate(coordinator)

    rows = api.get(AUDIT).data["results"]

    assert rows[0]["detail"] == "second"


@pytest.mark.django_db
def test_refused_only_filter_hides_allowed_rows(api, coordinator, organiser):
    record(organiser, "POST /api/events/", allowed=True)
    record_denied(organiser, action="GET /api/events/9/", detail="nope")
    api.force_authenticate(coordinator)

    unfiltered = api.get(AUDIT).data["results"]
    filtered = api.get(AUDIT, {"refused_only": "true"}).data["results"]

    assert len(unfiltered) == 2
    assert len(filtered) == 1
    assert filtered[0]["allowed"] is False


@pytest.mark.django_db
def test_rows_can_be_narrowed_to_one_actor(api, coordinator, organiser, other_organiser):
    record_denied(organiser, action="GET /api/events/1/", detail="acme")
    record_denied(other_organiser, action="GET /api/events/2/", detail="globex")
    api.force_authenticate(coordinator)

    rows = api.get(AUDIT, {"actor": str(organiser.pk)}).data["results"]

    assert len(rows) == 1
    assert rows[0]["detail"] == "acme"


@pytest.mark.django_db
def test_a_non_numeric_actor_filter_is_ignored_rather_than_erroring(api, coordinator, organiser):
    record_denied(organiser, action="GET /api/events/1/", detail="acme")
    api.force_authenticate(coordinator)

    response = api.get(AUDIT, {"actor": "' OR 1=1 --"})

    assert response.status_code == 200
    assert len(response.data["results"]) == 1


@pytest.mark.django_db
def test_an_anonymous_row_reads_back_without_inventing_a_user(api, coordinator):
    from django.contrib.auth.models import AnonymousUser

    record_denied(AnonymousUser(), action="GET /api/events/1/")
    api.force_authenticate(coordinator)

    row = api.get(AUDIT).data["results"][0]

    assert row["actor"] is None
    assert row["actor_name"] == "Anonymous"
    assert row["actor_role"] is None


@pytest.mark.django_db
def test_a_user_without_a_name_reads_back_as_their_email(api, coordinator, organiser):
    organiser.first_name = ""
    organiser.last_name = ""
    organiser.save(update_fields=["first_name", "last_name"])
    record_denied(organiser, action="GET /api/events/1/", detail="x")
    api.force_authenticate(coordinator)

    row = api.get(AUDIT).data["results"][0]

    assert row["actor_name"] == organiser.email


@pytest.mark.django_db
def test_the_page_size_can_be_capped_by_the_caller(api, coordinator, organiser):
    for i in range(5):
        record_denied(organiser, action=f"GET /api/events/{i}/", detail=str(i))
    api.force_authenticate(coordinator)

    response = api.get(AUDIT, {"page_size": "2"})

    assert len(response.data["results"]) == 2
    assert response.data["count"] == 5


@pytest.mark.django_db
def test_the_audit_log_is_readable_as_a_string_for_the_admin(organiser, complete_draft):
    entry = record_denied(organiser, action="GET /api/events/1/", obj=complete_draft, detail="no")

    assert "refused" in str(entry)
    assert AuditLog.objects.count() == 1

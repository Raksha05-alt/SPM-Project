"""Service layer behaviour that the HTTP tests do not reach directly."""

import pytest

from apps.core.statuses import EventStatus, InvalidTransition
from apps.events.services import MissingMandatoryFields, submit_event, transition_event


@pytest.mark.django_db
def test_submitting_an_incomplete_draft_raises_with_the_field_names(incomplete_draft, organiser):
    with pytest.raises(MissingMandatoryFields) as exc:
        submit_event(incomplete_draft, organiser)

    assert "name" in exc.value.fields
    assert "expected_attendance" in exc.value.fields


@pytest.mark.django_db
def test_an_illegal_transition_raises_and_changes_nothing(complete_draft, coordinator):
    with pytest.raises(InvalidTransition):
        transition_event(complete_draft, EventStatus.COMPLETED, coordinator)

    complete_draft.refresh_from_db()
    assert complete_draft.status == EventStatus.DRAFT
    assert complete_draft.status_history.count() == 0


@pytest.mark.django_db
def test_submitted_at_is_set_once_and_not_overwritten(complete_draft, organiser, coordinator):
    submit_event(complete_draft, organiser)
    first = complete_draft.submitted_at

    transition_event(complete_draft, EventStatus.UNDER_REVIEW, coordinator)

    complete_draft.refresh_from_db()
    assert complete_draft.submitted_at == first
    assert complete_draft.status_history.count() == 2

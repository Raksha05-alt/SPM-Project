"""US-06.2 - the status machine itself, tested without going through HTTP."""

import pytest

from apps.core.statuses import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    EventStatus,
    InvalidTransition,
    describe,
    validate_transition,
)


def test_a_draft_may_be_submitted():
    validate_transition(EventStatus.DRAFT, EventStatus.SUBMITTED)


def test_a_draft_may_not_jump_straight_to_confirmed():
    with pytest.raises(InvalidTransition):
        validate_transition(EventStatus.DRAFT, EventStatus.CONFIRMED)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATUSES))
def test_a_terminal_status_has_no_way_out(terminal):
    assert ALLOWED_TRANSITIONS[terminal] == frozenset()
    with pytest.raises(InvalidTransition):
        validate_transition(terminal, EventStatus.SUBMITTED)


def test_every_status_is_declared_in_the_machine():
    assert set(ALLOWED_TRANSITIONS) == set(EventStatus.values)


def test_every_status_has_a_plain_language_description():
    for value in EventStatus.values:
        assert describe(value)["description"]


def test_the_error_message_names_both_statuses():
    with pytest.raises(InvalidTransition) as exc:
        validate_transition(EventStatus.COMPLETED, EventStatus.DRAFT)
    assert "Completed" in str(exc.value)
    assert "Draft" in str(exc.value)

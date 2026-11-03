"""Reuse the Safety fixtures, which approve arrangements through the real actions."""

from apps.safety.tests.conftest import (  # noqa: F401 - fixtures used by name
    planning_event,
    ready_event,
    safety_officer,
    second_safety_officer,
    tech,
    venue,
)

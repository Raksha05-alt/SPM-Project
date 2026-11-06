"""SCRUM-88 worker command lifecycle and operational feedback."""

from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import CommandError, call_command


def test_scrum88_worker_rejects_zero_interval_before_processing(monkeypatch):
    processor = Mock()
    monkeypatch.setattr(
        "apps.venues.management.commands.process_venue_holds.process_holds", processor
    )
    with pytest.raises(CommandError, match="at least one second"):
        call_command("process_venue_holds", interval=0)
    processor.assert_not_called()


def test_scrum88_one_shot_worker_reports_counts_and_exits(monkeypatch):
    processor = Mock(return_value=(2, 3))
    monkeypatch.setattr(
        "apps.venues.management.commands.process_venue_holds.process_holds", processor
    )
    output = StringIO()
    call_command("process_venue_holds", stdout=output)
    processor.assert_called_once_with()
    assert output.getvalue() == "Expired 2 hold(s), sent 3 reminder(s).\n"


def test_scrum88_watcher_reuses_fresh_connections_and_stops_cleanly(monkeypatch):
    prefix = "apps.venues.management.commands.process_venue_holds."
    processor = Mock(side_effect=[(0, 0), (1, 0)])
    close = Mock()
    pause = Mock(side_effect=[None, KeyboardInterrupt])
    for name, value in [
        ("process_holds", processor),
        ("close_old_connections", close),
        ("sleep", pause),
    ]:
        monkeypatch.setattr(prefix + name, value)
    output = StringIO()
    call_command("process_venue_holds", watch=True, interval=1, stdout=output)
    assert processor.call_count == close.call_count == 2
    assert [call.args for call in pause.call_args_list] == [(1,), (1,)]
    assert output.getvalue().splitlines() == [
        "Expired 1 hold(s), sent 0 reminder(s).",
        "Venue hold processing stopped.",
    ]

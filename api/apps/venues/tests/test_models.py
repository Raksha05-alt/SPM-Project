import pytest

from apps.venues.serializers import describe_hours
from apps.venues.tests.conftest import make_venue


@pytest.mark.django_db
def test_hours_with_no_operating_days_count_as_not_provided():
    import datetime

    venue = make_venue(opens_at=datetime.time(9), closes_at=datetime.time(17), operating_days=[])

    assert describe_hours(venue) is None


@pytest.mark.django_db
def test_a_venue_reads_as_its_name():
    assert str(make_venue()) == "Harbour Hall"

"""SCRUM-71 - As an Event Coordinator, I want the system to tell me when a venue does
not appear suitable for the event, so that I do not request a room that cannot hold
the attendance or support the layout.

Original acceptance criteria AC1-AC5 (7 October snapshot). AC4 needs a venue
request action, which does not exist yet; see docs/testing/SCRUM-71.md.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from apps.core.models import AuditLog
from apps.events.models import EventStatus
from apps.venues.suitability import Requirement, check_suitability
from apps.venues.tests.conftest import make_venue
from conftest import make_event

SGT = ZoneInfo("Asia/Singapore")
# 2 November 2026 is a Monday; 7 November 2026 is a Saturday.
MONDAY = (2026, 11, 2)
SATURDAY = (2026, 11, 7)
WEEKDAYS_ONLY = [0, 1, 2, 3, 4]


def at(day, hour, minute=0):
    return datetime(*day, hour, minute, tzinfo=SGT)


def suitable_venue(**overrides):
    data = {
        "name": "Harbour Hall",
        "capacity": 100,
        "layouts": ["THEATRE", "CLASSROOM"],
        "facilities": ["Projector", "Hearing loop"],
        "wheelchair_access": True,
        "opens_at": time(8, 0),
        "closes_at": time(22, 0),
        "operating_days": WEEKDAYS_ONLY,
    }
    data.update(overrides)
    return make_venue(**data)


def event_for(organiser, **overrides):
    data = {
        "status": EventStatus.APPROVED,
        "expected_attendance": 80,
        "required_layout": "THEATRE",
        "preferred_start": at(MONDAY, 9),
        "preferred_end": at(MONDAY, 17),
    }
    data.update(overrides)
    return make_event(organiser, **data)


def requirements(result):
    return [r.requirement for r in result.reasons]


def url(event, venue=None):
    base = f"/api/events/{event.pk}/venue-suitability/"
    return f"{base}{venue.pk}/" if venue else base


# AC1 - capacity --------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("attendance", "flagged"),
    [(99, False), (100, False), (101, True)],
    ids=["one-below-capacity", "exactly-capacity", "one-above-capacity"],
)
def test_ac1_attendance_above_capacity_is_flagged(organiser, attendance, flagged):
    venue = suitable_venue(capacity=100)
    event = event_for(organiser, expected_attendance=attendance)

    result = check_suitability(event, venue)

    assert (Requirement.CAPACITY in requirements(result)) is flagged
    assert result.suitable is not flagged


@pytest.mark.django_db
def test_ac1_the_capacity_reason_states_both_numbers(organiser):
    result = check_suitability(
        event_for(organiser, expected_attendance=101), suitable_venue(capacity=100)
    )

    assert result.reasons[0].message == (
        "Expected attendance of 101 exceeds the venue's maximum capacity of 100."
    )


# AC2 - layout and accessibility ----------------------------------------------


@pytest.mark.django_db
def test_ac2_an_unsupported_layout_is_flagged_with_its_name(organiser):
    venue = suitable_venue(layouts=["CLASSROOM", "BOARDROOM"])
    event = event_for(organiser, required_layout="BANQUET")

    result = check_suitability(event, venue)

    assert requirements(result) == [Requirement.LAYOUT]
    assert result.reasons[0].message == "The venue does not support the required Banquet layout."


@pytest.mark.django_db
def test_ac2_a_venue_with_no_layouts_recorded_does_not_meet_a_required_layout(organiser):
    result = check_suitability(event_for(organiser), suitable_venue(layouts=[]))

    assert requirements(result) == [Requirement.LAYOUT]


@pytest.mark.django_db
def test_ac2_no_layout_preference_is_not_checked(organiser):
    result = check_suitability(event_for(organiser, required_layout=""), suitable_venue(layouts=[]))

    assert result.suitable


@pytest.mark.django_db
def test_ac2_a_missing_accessibility_facility_is_flagged_by_name(organiser):
    venue = suitable_venue(facilities=["Projector"])

    result = check_suitability(event_for(organiser), venue, ["Hearing loop"])

    assert requirements(result) == [Requirement.ACCESSIBILITY]
    assert result.reasons[0].message == (
        "The venue does not offer the required accessibility facility: Hearing loop."
    )


@pytest.mark.django_db
def test_ac2_facilities_match_regardless_of_case_or_spacing(organiser):
    venue = suitable_venue(facilities=["Hearing loop"])

    result = check_suitability(event_for(organiser), venue, ["  hearing LOOP ", ""])

    assert result.suitable


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("wheelchair_access", "flagged"),
    [(True, False), (False, True), (None, True)],
    ids=["step-free", "not-step-free", "not-recorded"],
)
def test_ac2_wheelchair_access_uses_the_venue_record(organiser, wheelchair_access, flagged):
    venue = suitable_venue(wheelchair_access=wheelchair_access, facilities=[])

    result = check_suitability(event_for(organiser), venue, ["Wheelchair access"])

    assert (Requirement.ACCESSIBILITY in requirements(result)) is flagged


@pytest.mark.django_db
def test_ac2_each_missing_facility_gets_its_own_reason(organiser):
    venue = suitable_venue(facilities=[], wheelchair_access=False)

    result = check_suitability(
        event_for(organiser), venue, ["Wheelchair access", "Hearing loop", "hearing loop"]
    )

    assert [r.message for r in result.reasons] == [
        "The venue does not offer the required accessibility facility: Wheelchair access.",
        "The venue does not offer the required accessibility facility: Hearing loop.",
    ]


# AC3 - operating hours -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "end"),
    [(at(MONDAY, 8), at(MONDAY, 22)), (at(MONDAY, 9), at(MONDAY, 17))],
    ids=["exactly-opening-to-closing", "well-inside"],
)
def test_ac3_an_event_inside_operating_hours_passes(organiser, start, end):
    event = event_for(organiser, preferred_start=start, preferred_end=end)

    assert check_suitability(event, suitable_venue()).suitable


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (
            at(MONDAY, 7, 59),
            at(MONDAY, 12),
            "The event runs 07:59-12:00, outside the venue's operating hours of 08:00-22:00.",
        ),
        (
            at(MONDAY, 18),
            at(MONDAY, 22, 1),
            "The event runs 18:00-22:01, outside the venue's operating hours of 08:00-22:00.",
        ),
        (
            at(SATURDAY, 10),
            at(SATURDAY, 12),
            "The event falls on a Saturday, when the venue is closed.",
        ),
        (
            at(MONDAY, 20),
            datetime(2026, 11, 3, 2, 0, tzinfo=SGT),
            "The event runs overnight, outside the venue's operating hours of 08:00-22:00.",
        ),
    ],
    ids=["starts-before-opening", "ends-after-closing", "closed-day", "overnight"],
)
def test_ac3_an_event_outside_operating_hours_is_flagged(organiser, start, end, message):
    event = event_for(organiser, preferred_start=start, preferred_end=end)

    result = check_suitability(event, suitable_venue())

    assert requirements(result) == [Requirement.OPERATING_HOURS]
    assert result.reasons[0].message == message


@pytest.mark.django_db
def test_ac3_times_are_compared_in_singapore_time(organiser):
    # 01:00-09:00 UTC is 09:00-17:00 in Singapore.
    utc = ZoneInfo("UTC")
    event = event_for(
        organiser,
        preferred_start=datetime(*MONDAY, 1, 0, tzinfo=utc),
        preferred_end=datetime(*MONDAY, 9, 0, tzinfo=utc),
    )

    assert check_suitability(event, suitable_venue()).suitable


@pytest.mark.django_db
@pytest.mark.parametrize(
    "missing",
    [{"opens_at": None}, {"closes_at": None}, {"operating_days": []}],
    ids=["no-opening-time", "no-closing-time", "no-operating-days"],
)
def test_ac3_unrecorded_hours_cannot_confirm_the_timing(organiser, missing):
    result = check_suitability(event_for(organiser), suitable_venue(**missing))

    assert requirements(result) == [Requirement.OPERATING_HOURS]
    assert result.reasons[0].message == (
        "The venue's operating hours are not recorded, so the event timing cannot be confirmed."
    )


@pytest.mark.django_db
def test_ac3_an_event_without_times_is_not_checked_for_hours(organiser):
    event = event_for(organiser, preferred_start=None, preferred_end=None)

    assert check_suitability(event, suitable_venue(opens_at=None)).suitable


# AC1-3 together ---------------------------------------------------------------


@pytest.mark.django_db
def test_every_unmet_requirement_is_stated_at_once(organiser):
    venue = suitable_venue(capacity=50, layouts=["BOARDROOM"], facilities=[])
    event = event_for(
        organiser,
        expected_attendance=60,
        required_layout="THEATRE",
        preferred_start=at(SATURDAY, 10),
        preferred_end=at(SATURDAY, 12),
    )

    result = check_suitability(event, venue, ["Hearing loop"])

    assert not result.suitable
    assert requirements(result) == [
        Requirement.CAPACITY,
        Requirement.LAYOUT,
        Requirement.ACCESSIBILITY,
        Requirement.OPERATING_HOURS,
    ]


# AC5 - a venue that meets every requirement -----------------------------------


@pytest.mark.django_db
def test_ac5_a_venue_meeting_every_requirement_has_no_warnings(organiser):
    event = event_for(organiser, expected_attendance=100)

    result = check_suitability(event, suitable_venue(), ["Wheelchair access", "Hearing loop"])

    assert result.suitable is True
    assert result.reasons == []


# API: the check an Event Coordinator runs --------------------------------------


@pytest.mark.django_db
def test_api_one_venue_returns_its_reasons(signed_in_coordinator, organiser):
    venue = suitable_venue(capacity=50)
    event = event_for(organiser, expected_attendance=60)

    response = signed_in_coordinator.get(url(event, venue))

    assert response.status_code == 200
    assert response.data == {
        "venue": venue.pk,
        "venue_name": "Harbour Hall",
        "suitable": False,
        "reasons": [
            {
                "requirement": "CAPACITY",
                "message": "Expected attendance of 60 exceeds the venue's maximum capacity of 50.",
            }
        ],
    }


@pytest.mark.django_db
def test_api_ac5_a_suitable_venue_has_no_reasons(signed_in_coordinator, organiser):
    venue = suitable_venue()
    response = signed_in_coordinator.get(url(event_for(organiser), venue))

    assert response.data["suitable"] is True
    assert response.data["reasons"] == []


@pytest.mark.django_db
def test_api_lists_every_venue_for_the_event(signed_in_coordinator, organiser):
    big = suitable_venue(name="Big Hall", capacity=500)
    small = suitable_venue(name="Small Room", capacity=10)
    event = event_for(organiser, expected_attendance=80)

    response = signed_in_coordinator.get(url(event))

    assert response.status_code == 200
    assert response.data["event"] == event.pk
    by_id = {v["venue"]: v for v in response.data["venues"]}
    assert by_id[big.pk]["suitable"] is True
    assert by_id[small.pk]["suitable"] is False
    assert [r["requirement"] for r in by_id[small.pk]["reasons"]] == ["CAPACITY"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "?facilities=Hearing%20loop&facilities=Wheelchair%20access",
        "?facilities=Hearing%20loop,Wheelchair%20access",
    ],
    ids=["repeated", "comma-separated"],
)
def test_api_required_facilities_come_from_the_query(signed_in_coordinator, organiser, query):
    venue = suitable_venue(facilities=[], wheelchair_access=False)
    event = event_for(organiser)

    response = signed_in_coordinator.get(url(event) + query)

    assert response.data["required_facilities"] == ["Hearing loop", "Wheelchair access"]
    (result,) = response.data["venues"]
    assert result["venue"] == venue.pk
    reasons = result["reasons"]
    assert [r["requirement"] for r in reasons] == ["ACCESSIBILITY", "ACCESSIBILITY"]


@pytest.mark.django_db
def test_api_a_draft_is_not_visible_to_coordinators(signed_in_coordinator, organiser):
    draft = event_for(organiser, status=EventStatus.DRAFT)

    assert signed_in_coordinator.get(url(draft, suitable_venue())).status_code == 404


@pytest.mark.django_db
def test_api_an_unknown_venue_is_not_found(signed_in_coordinator, organiser):
    response = signed_in_coordinator.get(
        f"/api/events/{event_for(organiser).pk}/venue-suitability/999999/"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_api_the_check_does_not_change_the_venue_or_event(signed_in_coordinator, organiser):
    venue = suitable_venue(capacity=50)
    event = event_for(organiser, expected_attendance=60)
    before = (venue.updated_at, event.updated_at, event.status)

    signed_in_coordinator.get(url(event, venue))

    venue.refresh_from_db()
    event.refresh_from_db()
    assert (venue.updated_at, event.updated_at, event.status) == before


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["organiser", "attendee", "venue_staff", "tech_staff"])
def test_api_only_event_coordinators_may_check_suitability(api, request, organiser, fixture_name):
    user = request.getfixturevalue(fixture_name)
    event = event_for(organiser)
    api.force_authenticate(user)

    response = api.get(url(event, suitable_venue()))

    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_api_an_anonymous_caller_is_refused_and_recorded(api, organiser):
    event = event_for(organiser)

    response = api.get(url(event))

    assert response.status_code in (401, 403)
    assert AuditLog.objects.filter(actor=None, allowed=False).exists()

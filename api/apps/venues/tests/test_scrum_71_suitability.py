"""SCRUM-71 - As an Event Coordinator, I want the system to tell me when a venue does
not appear suitable for the event, so that I do not request a room that cannot hold
the attendance or support the layout.

Sprint 3 gate G07. Each test is named after the acceptance criterion it verifies;
the S3-SCRUM-71 case IDs are in docs/test-cases/S3-SCRUM-71-suitability.csv.

* AC1-AC3, AC5: the shared assessment and the coordinator's API.
* AC4: the ``ensure_suitable`` guard is tested here against real booking-contract
  records; the request endpoint that calls it is SCRUM-11 (gate G09), where the
  end-to-end refusal test completes.
* AC6 (setup/turnaround buffer warning) is scheduled for Sprint 4 (SCRUM-85) and
  has no test here.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.venues.availability import availability, within_operating_hours
from apps.venues.bookings import create_booking_record
from apps.venues.models import LayoutType, VenueBlock, VenueBooking
from apps.venues.suitability import (
    Requirement,
    Requirements,
    VenueUnsuitable,
    assess,
    check_suitability,
    ensure_suitable,
)
from apps.venues.suitability_views import NOT_CHECKED
from apps.venues.tests.conftest import make_venue
from conftest import _make_user, make_event

SGT = ZoneInfo("Asia/Singapore")
# 2 November 2026 is a Monday; 7 November 2026 is a Saturday.
MONDAY = (2026, 11, 2)
SATURDAY = (2026, 11, 7)
WEEKDAYS_ONLY = [0, 1, 2, 3, 4]
HOURS_UNRECORDED = (
    "The venue's operating hours are not recorded, so the event timing cannot be confirmed."
)


def at(day, hour, minute=0, second=0):
    return datetime(*day, hour, minute, second, tzinfo=SGT)


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


@pytest.fixture
def event_for(organiser, coordinator):
    """An approved event assigned to the signed-in coordinator, with overrides."""

    def build(**overrides):
        data = {
            "status": EventStatus.APPROVED,
            "coordinator": coordinator,
            "expected_attendance": 80,
            "required_layout": "THEATRE",
            "preferred_start": at(MONDAY, 9),
            "preferred_end": at(MONDAY, 17),
        }
        data.update(overrides)
        return make_event(organiser, **data)

    return build


def requirements(result):
    return [r.requirement for r in result.reasons]


def url(event, venue=None, query=""):
    base = f"/api/events/{event.pk}/venue-suitability/"
    return (f"{base}{venue.pk}/" if venue else base) + query


# AC1 - capacity --------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("capacity", "flagged"),
    [(59, True), (60, False), (61, False)],
    ids=["capacity-59", "capacity-60-equal", "capacity-61"],
)
def test_ac1_attendance_60_against_capacities_59_60_61(event_for, capacity, flagged):
    """S3-71-01: capacity exactly equal to attendance is suitable."""
    result = check_suitability(event_for(expected_attendance=60), suitable_venue(capacity=capacity))

    assert (Requirement.CAPACITY in requirements(result)) is flagged
    assert result.suitable is not flagged


@pytest.mark.django_db
def test_ac1_the_capacity_reason_states_both_numbers(event_for):
    result = check_suitability(event_for(expected_attendance=101), suitable_venue(capacity=100))

    assert result.reasons[0].message == (
        "Expected attendance of 101 exceeds the venue's maximum capacity of 100."
    )


# AC2 - layout, accessibility and required facilities -------------------------


@pytest.mark.django_db
def test_ac2_an_unsupported_layout_is_flagged_with_its_catalogue_name(event_for):
    venue = suitable_venue(layouts=["CLASSROOM", "BOARDROOM"])

    result = check_suitability(event_for(required_layout="BANQUET"), venue)

    assert requirements(result) == [Requirement.LAYOUT]
    assert result.reasons[0].message == "The venue does not support the required Banquet layout."


@pytest.mark.django_db
def test_ac2_a_renamed_layout_is_reported_by_its_current_name(event_for):
    LayoutType.objects.filter(code="BANQUET").update(name="Banquet rounds")

    result = check_suitability(event_for(required_layout="BANQUET"), suitable_venue())

    assert result.reasons[0].message == (
        "The venue does not support the required Banquet rounds layout."
    )


@pytest.mark.django_db
def test_ac2_a_layout_added_to_the_catalogue_is_checked_like_any_other(event_for):
    LayoutType.objects.create(code="CABARET", name="Cabaret", sort_order=9)
    event = event_for(required_layout="CABARET")

    assert check_suitability(event, suitable_venue(layouts=["CABARET"])).suitable
    assert requirements(check_suitability(event, suitable_venue(name="Other"))) == [
        Requirement.LAYOUT
    ]


@pytest.mark.django_db
def test_ac2_a_retired_layout_already_on_the_event_is_still_assessed(event_for):
    LayoutType.objects.filter(code="BANQUET").update(is_active=False)
    event = event_for(required_layout="BANQUET")

    assert check_suitability(event, suitable_venue(layouts=["BANQUET"])).suitable
    assert check_suitability(event, suitable_venue(name="Other")).reasons[0].message == (
        "The venue does not support the required Banquet layout."
    )


@pytest.mark.django_db
def test_ac2_a_venue_with_no_layouts_recorded_does_not_meet_a_required_layout(event_for):
    result = check_suitability(event_for(), suitable_venue(layouts=[]))

    assert requirements(result) == [Requirement.LAYOUT]


@pytest.mark.django_db
def test_ac2_no_layout_preference_is_not_checked(event_for):
    result = check_suitability(event_for(required_layout=""), suitable_venue(layouts=[]))

    assert result.suitable


@pytest.mark.django_db
def test_ac2_a_missing_required_facility_is_flagged_by_name(event_for):
    venue = suitable_venue(facilities=["Projector"])

    result = check_suitability(event_for(), venue, ["Hearing loop"])

    assert requirements(result) == [Requirement.FACILITY]
    assert result.reasons[0].message == (
        "The venue does not offer the required facility: Hearing loop."
    )


@pytest.mark.django_db
def test_ac2_facilities_match_regardless_of_case_or_spacing(event_for):
    venue = suitable_venue(facilities=["Hearing loop"])

    result = check_suitability(event_for(), venue, ["  hearing LOOP ", ""])

    assert result.suitable


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("wheelchair_access", "message"),
    [
        (True, None),
        (False, "The venue does not have the required wheelchair access."),
        (None, "The venue's wheelchair access is not recorded, so it cannot be confirmed."),
    ],
    ids=["step-free", "not-step-free", "not-recorded"],
)
def test_ac2_required_wheelchair_access_uses_the_venue_record(
    event_for, wheelchair_access, message
):
    venue = suitable_venue(wheelchair_access=wheelchair_access, facilities=[])

    result = check_suitability(event_for(), venue, wheelchair_access_required=True)

    assert [r.message for r in result.reasons] == ([message] if message else [])
    if message:
        assert requirements(result) == [Requirement.ACCESSIBILITY]


@pytest.mark.django_db
def test_ac2_wheelchair_access_typed_as_a_facility_is_the_same_requirement(event_for):
    venue = suitable_venue(wheelchair_access=False, facilities=[])

    result = check_suitability(event_for(), venue, ["wheelchair ACCESS"])

    assert requirements(result) == [Requirement.ACCESSIBILITY]


@pytest.mark.django_db
def test_ac2_an_unrecorded_venue_listing_wheelchair_access_as_a_facility_meets_it(event_for):
    venue = suitable_venue(wheelchair_access=None, facilities=["Wheelchair access"])

    assert check_suitability(event_for(), venue, wheelchair_access_required=True).suitable


@pytest.mark.django_db
def test_ac2_wheelchair_access_not_required_is_not_checked(event_for):
    assert check_suitability(event_for(), suitable_venue(wheelchair_access=None)).suitable


@pytest.mark.django_db
def test_ac2_each_missing_requirement_gets_its_own_reason(event_for):
    venue = suitable_venue(facilities=[], wheelchair_access=False)

    result = check_suitability(
        event_for(), venue, ["Wheelchair access", "Hearing loop", "hearing loop", "Stage"]
    )

    assert [r.message for r in result.reasons] == [
        "The venue does not have the required wheelchair access.",
        "The venue does not offer the required facility: Hearing loop.",
        "The venue does not offer the required facility: Stage.",
    ]


# AC3 - operating hours -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "end"),
    [(at(MONDAY, 8), at(MONDAY, 22)), (at(MONDAY, 9), at(MONDAY, 17))],
    ids=["exactly-opening-to-closing", "well-inside"],
)
def test_ac3_an_event_inside_operating_hours_passes(event_for, start, end):
    event = event_for(preferred_start=start, preferred_end=end)

    assert check_suitability(event, suitable_venue()).suitable


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (
            at(MONDAY, 7, 59, 59),
            at(MONDAY, 12),
            "The event runs 07:59:59-12:00, outside the venue's operating hours of 08:00-22:00.",
        ),
        (
            at(MONDAY, 18),
            at(MONDAY, 22, 0, 1),
            "The event runs 18:00-22:00:01, outside the venue's operating hours of 08:00-22:00.",
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
        (at(MONDAY, 12), at(MONDAY, 10), "The event ends before it starts."),
    ],
    ids=[
        "one-second-before-opening",
        "one-second-after-closing",
        "closed-day",
        "overnight",
        "reversed",
    ],
)
def test_ac3_an_event_outside_operating_hours_is_flagged(event_for, start, end, message):
    """S3-71-03: one second outside the hours fails."""
    result = check_suitability(
        event_for(preferred_start=start, preferred_end=end), suitable_venue()
    )

    assert requirements(result) == [Requirement.OPERATING_HOURS]
    assert result.reasons[0].message == message


@pytest.mark.django_db
def test_ac3_times_are_compared_in_singapore_time(event_for):
    # 01:00-09:00 UTC is 09:00-17:00 in Singapore.
    utc = ZoneInfo("UTC")
    event = event_for(
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
def test_ac3_unrecorded_hours_cannot_confirm_the_timing(event_for, missing):
    result = check_suitability(event_for(), suitable_venue(**missing))

    assert requirements(result) == [Requirement.OPERATING_HOURS]
    assert result.reasons[0].message == HOURS_UNRECORDED


@pytest.mark.django_db
def test_ac3_an_event_without_times_is_not_checked_for_hours(event_for):
    event = event_for(preferred_start=None, preferred_end=None)

    assert check_suitability(event, suitable_venue(opens_at=None)).suitable


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (at(MONDAY, 8), at(MONDAY, 22)),
        (at(MONDAY, 7, 59, 59), at(MONDAY, 12)),
        (at(MONDAY, 18), at(MONDAY, 22, 0, 1)),
        (at(SATURDAY, 10), at(SATURDAY, 12)),
        (at(MONDAY, 20), datetime(2026, 11, 3, 2, 0, tzinfo=SGT)),
    ],
    ids=["inside", "early", "late", "closed-day", "overnight"],
)
def test_ac3_suitability_and_availability_share_one_operating_hours_rule(event_for, start, end):
    venue = suitable_venue()
    result = check_suitability(event_for(preferred_start=start, preferred_end=end), venue)

    assert (Requirement.OPERATING_HOURS not in requirements(result)) is within_operating_hours(
        venue, start, end
    )


# AC1-3 together ---------------------------------------------------------------


@pytest.mark.django_db
def test_every_unmet_requirement_is_stated_at_once(event_for):
    venue = suitable_venue(capacity=50, layouts=["BOARDROOM"], facilities=[])
    event = event_for(
        expected_attendance=60,
        required_layout="THEATRE",
        preferred_start=at(SATURDAY, 10),
        preferred_end=at(SATURDAY, 12),
    )

    result = check_suitability(event, venue, ["Hearing loop"], wheelchair_access_required=True)

    assert not result.suitable
    assert requirements(result) == [
        Requirement.CAPACITY,
        Requirement.LAYOUT,
        Requirement.FACILITY,
        Requirement.OPERATING_HOURS,
    ]


# AC4 - the guard the booking request action uses -------------------------------


def booking_for(event, venue, **overrides):
    values = {
        "requested_by": event.coordinator,
        "event": event,
        "venue": venue,
        "starts_at": at(MONDAY, 10),
        "ends_at": at(MONDAY, 12),
        "attendance": 60,
        "layout": "THEATRE",
        "required_facilities": ["Projector"],
        "wheelchair_access_required": True,
    }
    values.update(overrides)
    return create_booking_record(**values)


@pytest.mark.django_db
def test_ac4_an_unsuitable_venue_is_refused_with_every_reason(event_for):
    """S3-71-04 (service part): the requirements come from the stored booking
    request, so the guard does not depend on the coordinator visiting a page."""
    venue = suitable_venue(capacity=50, layouts=["BOARDROOM"], wheelchair_access=None)
    booking = booking_for(event_for(), venue)

    with pytest.raises(VenueUnsuitable) as refused:
        ensure_suitable(venue, Requirements.for_booking(booking))

    assert [r.requirement for r in refused.value.reasons] == [
        Requirement.CAPACITY,
        Requirement.LAYOUT,
        Requirement.ACCESSIBILITY,
    ]
    assert str(refused.value).startswith("Harbour Hall does not meet this event's requirements:")


@pytest.mark.django_db
def test_ac4_a_suitable_venue_passes_the_guard(event_for):
    venue = suitable_venue()
    booking = booking_for(event_for(), venue)

    assert ensure_suitable(venue, Requirements.for_booking(booking)).suitable


@pytest.mark.django_db
def test_ac4_the_guard_reads_values_a_request_is_about_to_save(event_for):
    """The request action can check its cleaned values before creating the row."""
    venue = suitable_venue(capacity=50)

    class Cleaned:
        attendance = 60
        layout = ""
        required_facilities = None
        wheelchair_access_required = False
        starts_at = at(MONDAY, 10)
        ends_at = at(MONDAY, 12)

    with pytest.raises(VenueUnsuitable):
        ensure_suitable(venue, Requirements.for_booking(Cleaned))
    assert not VenueBooking.objects.exists()


# AC5 - a venue that meets every requirement -----------------------------------


@pytest.mark.django_db
def test_ac5_a_venue_meeting_every_requirement_has_no_warnings(event_for):
    event = event_for(expected_attendance=100)

    result = check_suitability(event, suitable_venue(), ["Hearing loop"], True)

    assert result.suitable is True
    assert result.reasons == []


# Suitability is not availability ----------------------------------------------


@pytest.mark.django_db
def test_a_blocked_or_out_of_service_room_can_still_be_suitable(event_for):
    venue = suitable_venue(in_service=False)
    event = event_for()
    VenueBlock.objects.create(
        venue=venue,
        reason="Repainting",
        starts_at=event.preferred_start,
        ends_at=event.preferred_end,
    )

    assert assess(venue, Requirements.for_event(event)).suitable
    assert availability(venue, event.preferred_start, event.preferred_end)["available"] is False


# API: the check the assigned Event Coordinator runs ----------------------------


@pytest.mark.django_db
def test_api_one_venue_returns_its_reasons(signed_in_coordinator, event_for):
    venue = suitable_venue(capacity=50)
    event = event_for(expected_attendance=60)

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
        "in_service": True,
    }


@pytest.mark.django_db
def test_api_ac5_a_suitable_venue_has_no_reasons(signed_in_coordinator, event_for):
    response = signed_in_coordinator.get(url(event_for(), suitable_venue()))

    assert response.data["suitable"] is True
    assert response.data["reasons"] == []


@pytest.mark.django_db
def test_api_lists_every_venue_with_the_requirements_used(signed_in_coordinator, event_for):
    big = suitable_venue(name="Big Hall", capacity=500)
    small = suitable_venue(name="Small Room", capacity=10, in_service=False)
    event = event_for(expected_attendance=80)

    response = signed_in_coordinator.get(url(event))

    assert response.status_code == 200
    assert response.data["event"] == event.pk
    assert response.data["requirements"]["attendance"] == 80
    assert response.data["requirements"]["layout_name"] == "Theatre"
    assert response.data["not_checked"] == NOT_CHECKED
    by_id = {v["venue"]: v for v in response.data["venues"]}
    assert by_id[big.pk]["suitable"] is True
    assert by_id[small.pk]["suitable"] is False
    assert by_id[small.pk]["in_service"] is False
    assert [r["requirement"] for r in by_id[small.pk]["reasons"]] == ["CAPACITY"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "?facilities=Hearing%20loop&facilities=Stage&wheelchair=true",
        "?facilities=Hearing%20loop,Stage&wheelchair=true",
        "?facilities=Hearing%20loop,Stage,Wheelchair%20access",
    ],
    ids=["repeated", "comma-separated", "wheelchair-as-facility"],
)
def test_api_requirements_come_from_the_query(signed_in_coordinator, event_for, query):
    venue = suitable_venue(facilities=[], wheelchair_access=False)

    response = signed_in_coordinator.get(url(event_for(), query=query))

    assert response.data["requirements"]["required_facilities"] == ["Hearing loop", "Stage"]
    assert response.data["requirements"]["wheelchair_access_required"] is True
    (result,) = response.data["venues"]
    assert result["venue"] == venue.pk
    assert [r["requirement"] for r in result["reasons"]] == [
        "ACCESSIBILITY",
        "FACILITY",
        "FACILITY",
    ]


@pytest.mark.django_db
def test_api_an_invalid_wheelchair_value_is_refused(signed_in_coordinator, event_for):
    response = signed_in_coordinator.get(url(event_for(), query="?wheelchair=maybe"))

    assert response.status_code == 400
    assert response.data["wheelchair"] == ["Use true or false."]


@pytest.mark.django_db
def test_api_an_unknown_venue_or_event_is_not_found(signed_in_coordinator, event_for):
    event = event_for()

    assert signed_in_coordinator.get(f"{url(event)}999999/").status_code == 404
    assert signed_in_coordinator.get("/api/events/999999/venue-suitability/").status_code == 404


@pytest.mark.django_db
def test_api_the_check_does_not_change_the_venue_or_event(signed_in_coordinator, event_for):
    venue = suitable_venue(capacity=50)
    event = event_for(expected_attendance=60)
    before = (venue.updated_at, event.updated_at, event.status)

    signed_in_coordinator.get(url(event, venue))

    venue.refresh_from_db()
    event.refresh_from_db()
    assert (venue.updated_at, event.updated_at, event.status) == before


# API: who may run it ------------------------------------------------------------


@pytest.mark.django_db
def test_api_a_draft_is_refused_and_audited(signed_in_coordinator, coordinator, event_for):
    draft = event_for(status=EventStatus.DRAFT)

    assert signed_in_coordinator.get(url(draft, suitable_venue())).status_code == 403
    assert AuditLog.objects.filter(actor=coordinator, allowed=False).exists()


@pytest.mark.django_db
def test_api_another_coordinator_is_refused_and_audited(api, second_coordinator, event_for):
    """SCRUM-89 ownership: only the event's current coordinator may check it."""
    api.force_authenticate(second_coordinator)

    response = api.get(url(event_for()))

    assert response.status_code == 403
    assert AuditLog.objects.get(actor=second_coordinator, allowed=False).detail == (
        "draft event or coordinator is not assigned to this event"
    )


@pytest.mark.django_db
def test_api_a_reassigned_coordinator_loses_access(
    signed_in_coordinator, second_coordinator, event_for
):
    event = event_for()
    event.coordinator = second_coordinator
    event.save(update_fields=["coordinator"])

    assert signed_in_coordinator.get(url(event)).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role_fixture", ["organiser", "attendee", "venue_staff", "tech_staff", "lead"]
)
def test_api_only_event_coordinators_may_check_suitability(api, request, event_for, role_fixture):
    user = request.getfixturevalue(role_fixture)
    api.force_authenticate(user)

    response = api.get(url(event_for(), suitable_venue()))

    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()


@pytest.mark.django_db
def test_api_a_safety_officer_is_refused(api, event_for):
    from apps.accounts.models import Role

    officer = _make_user("safety@connectsphere.example", Role.SAFETY_OFFICER)
    api.force_authenticate(officer)

    assert api.get(url(event_for())).status_code == 403


@pytest.mark.django_db
def test_api_an_anonymous_caller_is_refused_and_recorded(api, event_for):
    response = api.get(url(event_for()))

    assert response.status_code in (401, 403)
    assert AuditLog.objects.filter(actor=None, allowed=False).exists()

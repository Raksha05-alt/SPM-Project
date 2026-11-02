"""INT-02 - affected-layout warning (Sprint 3 gate G13; SCRUM-5 AC4).

When Venue Staff remove a supported layout from a venue, warn which approved
bookings at that venue use it. The change needs an explicit confirmation, and
the bookings are kept either way: no deletion and no change to their layout or
history. This is distinct from retiring a layout from the SCRUM-91 catalogue.

Every booking here is made Approved through the real SCRUM-72 action.
Case IDs follow the Sprint 3 guide: S3-INT-02-<case>.
"""

import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.core.models import AuditLog
from apps.core.statuses import EventStatus
from apps.venues.bookings import (
    approve_booking,
    create_booking_record,
    reject_booking,
    withdraw_booking,
)
from apps.venues.models import BookingStatus, Venue, VenueBooking, VenueBookingHistory
from apps.venues.suitability import VenueUnsuitable
from apps.venues.tests.conftest import make_venue
from conftest import make_event

SGT = ZoneInfo("Asia/Singapore")
START = datetime.datetime(2027, 3, 1, 10, 0, tzinfo=SGT)
END = datetime.datetime(2027, 3, 1, 12, 0, tzinfo=SGT)


def venue_url(venue):
    return f"/api/venues/{venue.pk}/"


@pytest.fixture
def hall(db):
    """Capacity 60, Theatre and Banquet, open 08:00-22:00 daily."""
    return make_venue(
        name="Harbour Hall",
        capacity=60,
        layouts=["THEATRE", "BANQUET"],
        facilities=["Video conferencing"],
        wheelchair_access=True,
        opens_at=datetime.time(8),
        closes_at=datetime.time(22),
    )


@pytest.fixture
def staff_api(api, venue_staff):
    api.force_authenticate(venue_staff)
    return api


def requested(organiser, coordinator, venue, *, name="Annual Gala", **overrides):
    event = make_event(organiser, status=EventStatus.PLANNING, coordinator=coordinator, name=name)
    values = {"starts_at": START, "ends_at": END, "attendance": 60, "layout": "THEATRE"}
    values.update(overrides)
    return create_booking_record(requested_by=coordinator, event=event, venue=venue, **values)


def approved(organiser, coordinator, venue_staff, venue, **overrides):
    return approve_booking(requested(organiser, coordinator, venue, **overrides), venue_staff)


@pytest.fixture
def gala(organiser, coordinator, venue_staff, hall):
    """An approved Theatre booking at Harbour Hall, 1 Mar 2027 10:00-12:00."""
    return approved(organiser, coordinator, venue_staff, hall)


def snapshot(booking):
    fresh = VenueBooking.objects.get(pk=booking.pk)
    history = list(
        VenueBookingHistory.objects.filter(booking=booking).values_list(
            "from_status", "to_status", "actor_id", "reason"
        )
    )
    return (
        fresh.status,
        fresh.layout,
        fresh.venue_id,
        fresh.starts_at,
        fresh.ends_at,
        fresh.decided_by_id,
        history,
    )


# S3-INT-02-01 - removing a layout no approved booking uses saves with no warning.


@pytest.mark.django_db
def test_s3_int02_01_removing_an_unused_layout_saves_without_warning(staff_api, hall, gala):
    response = staff_api.patch(venue_url(hall), {"layouts": ["THEATRE"]}, format="json")

    assert response.status_code == 200
    assert "affected_bookings" not in response.data
    hall.refresh_from_db()
    assert hall.layouts == ["THEATRE"]


@pytest.mark.django_db
def test_s3_int02_01_a_venue_with_no_bookings_saves_without_warning(staff_api, hall):
    response = staff_api.patch(venue_url(hall), {"layouts": []}, format="json")

    assert response.status_code == 200
    hall.refresh_from_db()
    assert hall.layouts == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "layouts",
    [["THEATRE", "BANQUET"], ["THEATRE", "BANQUET", "CLASSROOM"]],
    ids=["unchanged", "layout-added"],
)
def test_s3_int02_01_keeping_or_adding_layouts_never_warns(staff_api, hall, gala, layouts):
    response = staff_api.patch(venue_url(hall), {"layouts": layouts}, format="json")

    assert response.status_code == 200


@pytest.mark.django_db
def test_s3_int02_01_editing_other_details_never_warns(staff_api, hall, gala):
    response = staff_api.patch(venue_url(hall), {"capacity": 80}, format="json")

    assert response.status_code == 200
    hall.refresh_from_db()
    assert (hall.capacity, hall.layouts) == (80, ["THEATRE", "BANQUET"])


# S3-INT-02-02 - removing a used layout is held back with a warning naming the bookings.


@pytest.mark.django_db
def test_s3_int02_02_removing_a_used_layout_warns_and_saves_nothing(staff_api, hall, gala):
    before = snapshot(gala)

    response = staff_api.patch(venue_url(hall), {"layouts": ["BANQUET"]}, format="json")

    assert response.status_code == 409
    assert response.data["detail"] == (
        "Removing Theatre from Harbour Hall affects 1 approved booking. "
        "The booking will be kept. Confirm to remove the layout anyway."
    )
    [row] = response.data["affected_bookings"]
    assert row["booking"] == gala.pk
    assert row["event"] == gala.event_id
    assert row["event_name"] == "Annual Gala"
    assert (row["layout"], row["layout_name"]) == ("THEATRE", "Theatre")
    assert row["starts_at"] == START
    assert row["ends_at"] == END
    # Nothing saved: a fresh read shows the venue and the booking unchanged.
    fresh = staff_api.get(venue_url(hall)).data
    assert fresh["layouts"] == ["THEATRE", "BANQUET"]
    assert snapshot(gala) == before


@pytest.mark.django_db
def test_s3_int02_02_the_warning_is_readable_over_the_wire(staff_api, hall, gala):
    response = staff_api.patch(venue_url(hall), {"layouts": ["BANQUET"]}, format="json")

    [row] = response.json()["affected_bookings"]
    # 10:00-12:00 Singapore is 02:00-04:00 UTC: compare instants, not formatting.
    assert datetime.datetime.fromisoformat(row["starts_at"]) == START
    assert datetime.datetime.fromisoformat(row["ends_at"]) == END


@pytest.mark.django_db
def test_s3_int02_02_other_changes_in_the_same_save_are_not_applied(staff_api, hall, gala):
    response = staff_api.patch(
        venue_url(hall), {"layouts": ["BANQUET"], "name": "Harbour Hall East"}, format="json"
    )

    assert response.status_code == 409
    hall.refresh_from_db()
    assert hall.name == "Harbour Hall"


@pytest.mark.django_db
def test_s3_int02_02_a_full_update_warns_the_same_way(staff_api, hall, gala):
    body = staff_api.get(venue_url(hall)).data
    body["layouts"] = ["BANQUET"]

    response = staff_api.put(venue_url(hall), body, format="json")

    assert response.status_code == 409
    assert [row["booking"] for row in response.data["affected_bookings"]] == [gala.pk]


@pytest.mark.django_db
def test_s3_int02_02_every_affected_booking_is_listed_in_date_order(
    staff_api, organiser, coordinator, venue_staff, hall, gala
):
    later = approved(
        organiser,
        coordinator,
        venue_staff,
        hall,
        name="Spring Dinner",
        layout="BANQUET",
        starts_at=START + datetime.timedelta(days=7),
        ends_at=END + datetime.timedelta(days=7),
    )

    response = staff_api.patch(venue_url(hall), {"layouts": []}, format="json")

    assert response.status_code == 409
    assert response.data["detail"].startswith(
        "Removing Theatre, Banquet from Harbour Hall affects 2 approved bookings."
    )
    rows = response.data["affected_bookings"]
    assert [(r["booking"], r["layout_name"]) for r in rows] == [
        (gala.pk, "Theatre"),
        (later.pk, "Banquet"),
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("confirm", [False, "true", 1, None])
def test_s3_int02_02_only_an_explicit_true_confirms(staff_api, hall, gala, confirm):
    response = staff_api.patch(
        venue_url(hall),
        {"layouts": ["BANQUET"], "confirm_layout_removal": confirm},
        format="json",
    )

    assert response.status_code == 409
    hall.refresh_from_db()
    assert hall.layouts == ["THEATRE", "BANQUET"]


# S3-INT-02-03 - confirming removes the layout and keeps the bookings untouched.


@pytest.mark.django_db
def test_s3_int02_03_confirmed_removal_keeps_the_booking(staff_api, venue_staff, hall, gala):
    before = snapshot(gala)

    response = staff_api.patch(
        venue_url(hall), {"layouts": ["BANQUET"], "confirm_layout_removal": True}, format="json"
    )

    assert response.status_code == 200
    assert response.data["layouts"] == ["BANQUET"]
    # Fresh reads: the venue changed; the booking, its layout and history did not.
    assert staff_api.get(venue_url(hall)).data["layouts"] == ["BANQUET"]
    assert snapshot(gala) == before
    booking = staff_api.get(f"/api/venue-bookings/{gala.pk}/").data
    assert (booking["status"], booking["layout"], booking["layout_name"]) == (
        BookingStatus.APPROVED,
        "THEATRE",
        "Theatre",
    )
    entry = AuditLog.objects.filter(actor=venue_staff, allowed=True).latest("pk")
    assert entry.detail == f"Layout removed; approved bookings kept: {gala.pk}"


@pytest.mark.django_db
def test_s3_int02_03_the_layout_catalogue_entry_is_not_retired(staff_api, hall, gala):
    staff_api.patch(
        venue_url(hall), {"layouts": ["BANQUET"], "confirm_layout_removal": True}, format="json"
    )

    # Removing one venue's layout is not SCRUM-91 retirement.
    layouts = {row["code"]: row for row in staff_api.get("/api/layouts/").data}
    assert layouts["THEATRE"]["is_active"] is True


@pytest.mark.django_db
def test_s3_int02_03_a_later_request_for_the_removed_layout_is_refused(
    organiser, coordinator, venue_staff, staff_api, hall, gala
):
    staff_api.patch(
        venue_url(hall), {"layouts": ["BANQUET"], "confirm_layout_removal": True}, format="json"
    )
    pending = requested(
        organiser,
        coordinator,
        hall,
        name="Board Offsite",
        starts_at=START + datetime.timedelta(days=14),
        ends_at=END + datetime.timedelta(days=14),
    )

    # SCRUM-71 - the venue no longer supports Theatre, so approval is refused.
    with pytest.raises(VenueUnsuitable):
        approve_booking(pending, venue_staff)
    assert VenueBooking.objects.get(pk=pending.pk).status == BookingStatus.PENDING


@pytest.mark.django_db
def test_s3_int02_03_an_audit_entry_without_affected_bookings_has_no_note(
    staff_api, venue_staff, hall, gala
):
    staff_api.patch(venue_url(hall), {"layouts": ["THEATRE"]}, format="json")

    entry = AuditLog.objects.filter(actor=venue_staff, allowed=True).latest("pk")
    assert entry.detail == ""


# S3-INT-02-04 - only approved bookings at this venue that have not ended count.


@pytest.mark.django_db
@pytest.mark.parametrize("outcome", ["pending", "rejected", "withdrawn"])
def test_s3_int02_04_requests_that_are_not_approved_are_not_affected(
    staff_api, organiser, coordinator, venue_staff, hall, outcome
):
    booking = requested(organiser, coordinator, hall)
    if outcome == "rejected":
        reject_booking(booking, venue_staff, "Closed for maintenance.")
    elif outcome == "withdrawn":
        withdraw_booking(booking=booking, actor=coordinator, expected_status=BookingStatus.PENDING)

    response = staff_api.patch(venue_url(hall), {"layouts": ["BANQUET"]}, format="json")

    assert response.status_code == 200
    assert VenueBooking.objects.get(pk=booking.pk).layout == "THEATRE"


@pytest.mark.django_db
def test_s3_int02_04_an_approved_booking_that_has_ended_is_not_affected(staff_api, hall, gala):
    VenueBooking.objects.filter(pk=gala.pk).update(
        starts_at=datetime.datetime(2020, 3, 1, 10, 0, tzinfo=SGT),
        ends_at=datetime.datetime(2020, 3, 1, 12, 0, tzinfo=SGT),
    )

    response = staff_api.patch(venue_url(hall), {"layouts": ["BANQUET"]}, format="json")

    assert response.status_code == 200


@pytest.mark.django_db
def test_s3_int02_04_bookings_at_another_venue_are_not_affected(
    staff_api, organiser, coordinator, venue_staff, hall
):
    other = make_venue(
        name="Skyline Room",
        capacity=60,
        layouts=["THEATRE"],
        opens_at=datetime.time(8),
        closes_at=datetime.time(22),
    )
    approved(organiser, coordinator, venue_staff, other)

    response = staff_api.patch(venue_url(hall), {"layouts": ["BANQUET"]}, format="json")

    assert response.status_code == 200


@pytest.mark.django_db
def test_s3_int02_04_a_booking_with_no_layout_preference_is_not_affected(
    staff_api, organiser, coordinator, venue_staff, hall
):
    approved(organiser, coordinator, venue_staff, hall, layout="")

    response = staff_api.patch(venue_url(hall), {"layouts": []}, format="json")

    assert response.status_code == 200


# S3-INT-02-05 - only Venue Staff change a venue's layouts.


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["coordinator", "organiser", "lead"])
def test_s3_int02_05_other_roles_cannot_remove_layouts(api, hall, gala, request, who):
    user = request.getfixturevalue(who)
    api.force_authenticate(user)

    response = api.patch(
        venue_url(hall), {"layouts": [], "confirm_layout_removal": True}, format="json"
    )

    assert response.status_code == 403
    assert AuditLog.objects.filter(actor=user, allowed=False).exists()
    assert Venue.objects.get(pk=hall.pk).layouts == ["THEATRE", "BANQUET"]

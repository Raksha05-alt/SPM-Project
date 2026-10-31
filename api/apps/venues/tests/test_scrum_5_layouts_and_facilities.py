"""SCRUM-5 - As Venue Staff, I want to record which room layouts and facilities
each venue supports, so that coordinators can match venues to the layout the
Event Organiser asked for.

AC4 (warn which confirmed bookings are affected when a layout is removed) is
blocked: this baseline has no booking records, so there is nothing to warn
about yet. It needs the booking slice agreed in the Sprint 2 implementation
guide before it can be implemented or tested.
"""

import pytest

from apps.core.models import AuditLog
from apps.venues.models import LayoutType, Venue
from apps.venues.tests.conftest import make_venue

VENUES = "/api/venues/"


def venue_url(venue):
    return f"{VENUES}{venue.pk}/"


# AC1 - select supported layouts from the agreed list --------------------------


@pytest.mark.django_db
def test_ac1_venue_staff_select_the_layouts_a_venue_supports(signed_in_venue_staff, venue):
    response = signed_in_venue_staff.patch(
        venue_url(venue), {"layouts": ["BANQUET", "CLASSROOM"]}, format="json"
    )

    assert response.status_code == 200
    venue.refresh_from_db()
    # Saved in the agreed list's order, whatever order they were ticked in.
    assert venue.layouts == ["CLASSROOM", "BANQUET"]
    assert response.data["layout_labels"] == ["Classroom", "Banquet"]


@pytest.mark.django_db
def test_ac1_every_layout_on_the_agreed_list_can_be_recorded(signed_in_venue_staff, venue):
    # SCRUM-91 replaced the fixed list with the catalogue, seeded with these five.
    seeded = list(LayoutType.objects.filter(is_active=True).values_list("code", flat=True))
    response = signed_in_venue_staff.patch(venue_url(venue), {"layouts": seeded}, format="json")

    assert response.status_code == 200
    venue.refresh_from_db()
    assert venue.layouts == ["CLASSROOM", "THEATRE", "BOARDROOM", "BANQUET", "EXHIBITION"]


@pytest.mark.django_db
def test_ac1_saved_layouts_are_read_back_unchanged(signed_in_venue_staff, venue):
    signed_in_venue_staff.patch(venue_url(venue), {"layouts": ["EXHIBITION"]}, format="json")

    fresh = signed_in_venue_staff.get(venue_url(venue))

    assert fresh.data["layouts"] == ["EXHIBITION"]
    assert fresh.data["layout_labels"] == ["Exhibition"]


@pytest.mark.django_db
def test_ac1_a_layout_ticked_twice_is_saved_once(signed_in_venue_staff, venue):
    signed_in_venue_staff.patch(
        venue_url(venue), {"layouts": ["THEATRE", "THEATRE"]}, format="json"
    )

    venue.refresh_from_db()
    assert venue.layouts == ["THEATRE"]


@pytest.mark.django_db
@pytest.mark.parametrize("bad", [["CABARET"], ["theatre"], ["THEATRE", "U_SHAPE"]])
def test_ac1_a_layout_outside_the_agreed_list_is_refused_and_nothing_is_saved(
    signed_in_venue_staff, venue, bad
):
    response = signed_in_venue_staff.patch(venue_url(venue), {"layouts": bad}, format="json")

    assert response.status_code == 400
    assert "Choose from Classroom, Theatre, Boardroom, Banquet, Exhibition" in str(
        response.data["layouts"]
    )
    venue.refresh_from_db()
    assert venue.layouts == ["THEATRE"]


@pytest.mark.django_db
def test_ac1_removing_every_layout_leaves_it_flagged_as_missing(signed_in_venue_staff, venue):
    response = signed_in_venue_staff.patch(venue_url(venue), {"layouts": []}, format="json")

    assert response.status_code == 200
    assert "Supported room layouts" in response.data["missing_information"]


@pytest.mark.django_db
def test_ac1_a_layout_change_records_who_made_it(signed_in_venue_staff, venue_staff, venue):
    signed_in_venue_staff.patch(venue_url(venue), {"layouts": ["BOARDROOM"]}, format="json")

    venue.refresh_from_db()
    assert venue.updated_by == venue_staff
    assert AuditLog.objects.filter(
        actor=venue_staff, allowed=True, action=f"PATCH {venue_url(venue)}"
    ).exists()


# AC2 - record facilities, including video-conferencing and accessibility -----


@pytest.mark.django_db
def test_ac2_venue_staff_record_video_conferencing_and_accessibility_facilities(
    signed_in_venue_staff, venue
):
    facilities = ["Video conferencing", "Hearing loop", "Step-free access", "Accessible toilet"]

    response = signed_in_venue_staff.patch(
        venue_url(venue),
        {
            "facilities": facilities,
            "wheelchair_access": True,
            "accessibility_notes": "Lift from the main lobby.",
        },
        format="json",
    )

    assert response.status_code == 200
    venue.refresh_from_db()
    assert venue.facilities == facilities
    assert venue.wheelchair_access is True
    assert venue.accessibility_notes == "Lift from the main lobby."
    fresh = signed_in_venue_staff.get(venue_url(venue)).data
    assert fresh["facilities"] == facilities


@pytest.mark.django_db
def test_ac2_facility_names_are_tidied_and_not_repeated(signed_in_venue_staff, venue):
    signed_in_venue_staff.patch(
        venue_url(venue),
        {"facilities": ["  Video conferencing ", "video CONFERENCING", "", "Projector"]},
        format="json",
    )

    venue.refresh_from_db()
    assert venue.facilities == ["Video conferencing", "Projector"]


@pytest.mark.django_db
@pytest.mark.parametrize("bad", ["Projector", [1, 2], [{"name": "Projector"}]])
def test_ac2_facilities_that_are_not_a_list_of_names_are_refused(signed_in_venue_staff, venue, bad):
    response = signed_in_venue_staff.patch(venue_url(venue), {"facilities": bad}, format="json")

    assert response.status_code == 400
    venue.refresh_from_db()
    assert venue.facilities == ["Projector"]


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["coordinator", "tech_staff", "organiser", "attendee"])
def test_ac1_ac2_only_venue_staff_can_change_layouts_or_facilities(
    api, request, venue, fixture_name
):
    user = request.getfixturevalue(fixture_name)
    api.force_authenticate(user)

    response = api.patch(
        venue_url(venue),
        {"layouts": ["BANQUET"], "facilities": ["Video conferencing"]},
        format="json",
    )

    assert response.status_code == 403
    venue.refresh_from_db()
    assert venue.layouts == ["THEATRE"]
    assert venue.facilities == ["Projector"]


# AC3 - a venue with a layout recorded is eligible for a layout search --------


@pytest.mark.django_db
def test_ac3_a_venue_with_the_layout_recorded_appears_in_a_layout_search(api, coordinator):
    theatre = make_venue(name="Harbour Hall", layouts=["THEATRE", "CLASSROOM"])
    make_venue(name="Garden Room", layouts=["BANQUET"])
    make_venue(name="Empty Annex", layouts=[])
    api.force_authenticate(coordinator)

    response = api.get(VENUES, {"layout": "THEATRE"})

    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [theatre.pk]


@pytest.mark.django_db
def test_ac3_a_venue_supporting_several_layouts_matches_each_of_them(api, coordinator):
    hall = make_venue(name="Harbour Hall", layouts=["THEATRE", "CLASSROOM", "BANQUET"])
    api.force_authenticate(coordinator)

    for layout in ("THEATRE", "CLASSROOM", "BANQUET"):
        ids = [row["id"] for row in api.get(VENUES, {"layout": layout}).data]
        assert ids == [hall.pk]
    assert api.get(VENUES, {"layout": "BOARDROOM"}).data == []


@pytest.mark.django_db
def test_ac3_a_layout_recorded_through_the_api_makes_the_venue_searchable(
    api, venue_staff, coordinator, venue
):
    api.force_authenticate(coordinator)
    assert api.get(VENUES, {"layout": "BOARDROOM"}).data == []

    api.force_authenticate(venue_staff)
    api.patch(venue_url(venue), {"layouts": ["THEATRE", "BOARDROOM"]}, format="json")

    api.force_authenticate(coordinator)
    ids = [row["id"] for row in api.get(VENUES, {"layout": "BOARDROOM"}).data]
    assert ids == [venue.pk]


@pytest.mark.django_db
def test_ac3_without_a_layout_every_venue_is_listed(api, coordinator):
    make_venue(name="Harbour Hall", layouts=["THEATRE"])
    make_venue(name="Empty Annex", layouts=[])
    api.force_authenticate(coordinator)

    assert len(api.get(VENUES).data) == 2
    assert len(api.get(VENUES, {"layout": ""}).data) == 2


@pytest.mark.django_db
def test_ac3_an_unknown_layout_is_refused_rather_than_matching_nothing(api, coordinator, venue):
    api.force_authenticate(coordinator)

    response = api.get(VENUES, {"layout": "CABARET"})

    assert response.status_code == 400
    assert "layout" in response.data


@pytest.mark.django_db
def test_ac3_the_shared_eligibility_rule_matches_exact_layout_values():
    hall = make_venue(name="Harbour Hall", layouts=["THEATRE"])
    make_venue(name="Garden Room", layouts=["BANQUET"])

    assert list(Venue.objects.supporting_layout("THEATRE")) == [hall]
    assert list(Venue.objects.supporting_layout("theatre")) == []


@pytest.mark.django_db
@pytest.mark.parametrize("fixture_name", ["organiser", "attendee"])
def test_ac3_clients_and_attendees_cannot_search_venues_by_layout(
    api, request, venue, fixture_name
):
    api.force_authenticate(request.getfixturevalue(fixture_name))

    assert api.get(VENUES, {"layout": "THEATRE"}).status_code == 403

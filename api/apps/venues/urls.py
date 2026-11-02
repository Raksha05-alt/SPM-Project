from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.venues.availability_views import (
    AvailableVenuesView,
    BlockDetailView,
    BlockHistoryView,
    BlockView,
    CalendarView,
    CompareAvailabilityView,
)
from apps.venues.booking_views import (
    EventVenueBookingsView,
    VenueBookingDecisionView,
    VenueBookingDetailView,
    VenueBookingInboxView,
    WithdrawVenueBookingView,
)
from apps.venues.discovery_views import (
    EventVenueShortlistItemView,
    EventVenueShortlistView,
    VenueSearchView,
)
from apps.venues.layout_views import LayoutTypeViewSet
from apps.venues.suitability_views import EventVenueSuitabilityView
from apps.venues.views import VenueViewSet

router = SimpleRouter()
router.register("venues", VenueViewSet, basename="venue")
router.register("layouts", LayoutTypeViewSet, basename="layout-type")

urlpatterns = [
    path(
        "events/<int:event_id>/venue-bookings/<int:booking_id>/withdraw/",
        WithdrawVenueBookingView.as_view(),
        name="withdraw-venue-booking",
    ),
    path("venues/available/", AvailableVenuesView.as_view()),
    path("venues/compare-availability/", CompareAvailabilityView.as_view()),
    path("venues/<int:pk>/availability/", CalendarView.as_view()),
    path("venues/<int:pk>/blocks/", BlockView.as_view()),
    path("venues/<int:pk>/blocks/history/", BlockHistoryView.as_view()),
    path("venues/<int:pk>/blocks/<int:block_pk>/", BlockDetailView.as_view()),
    path("venues/search/", VenueSearchView.as_view(), name="venue-search"),
    path(
        "events/<int:event_id>/venue-bookings/",
        EventVenueBookingsView.as_view(),
        name="event-venue-bookings",
    ),
    path("venue-bookings/", VenueBookingInboxView.as_view(), name="venue-booking-inbox"),
    # SCRUM-72 - Venue Staff respond to a booking request.
    path(
        "venue-bookings/<int:booking_id>/",
        VenueBookingDetailView.as_view(),
        name="venue-booking-detail",
    ),
    path(
        "venue-bookings/<int:booking_id>/approve/",
        VenueBookingDecisionView.as_view(decision="approve"),
        name="venue-booking-approve",
    ),
    path(
        "venue-bookings/<int:booking_id>/reject/",
        VenueBookingDecisionView.as_view(decision="reject"),
        name="venue-booking-reject",
    ),
    path(
        "events/<int:event_id>/venue-shortlist/",
        EventVenueShortlistView.as_view(),
        name="venue-shortlist",
    ),
    path(
        "events/<int:event_id>/venue-shortlist/<int:venue_id>/",
        EventVenueShortlistItemView.as_view(),
        name="venue-shortlist-item",
    ),
    path("", include(router.urls)),
    # SCRUM-71 - venue suitability for an event.
    path(
        "events/<int:event_id>/venue-suitability/",
        EventVenueSuitabilityView.as_view(),
        name="event-venue-suitability",
    ),
    path(
        "events/<int:event_id>/venue-suitability/<int:venue_id>/",
        EventVenueSuitabilityView.as_view(),
        name="event-venue-suitability-detail",
    ),
]

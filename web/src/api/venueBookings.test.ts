import { beforeEach, expect, it, vi } from "vitest";
import { request } from "./client";
import { approveBooking, listBookingInbox, listEventBookings, rejectBooking, removeVenueSession, requestVenue, withdrawVenue } from "./venueBookings";
import type { VenueBooking } from "../types";
vi.mock("./client", () => ({ request: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
it("SCRUM-87 client contract: session identity and replacement are carried in the event-scoped request", () => {
  const input = { venue: 3, session_id: 11, replaces_id: 2, starts_at: "2027-06-08T02:00:00Z", ends_at: "2027-06-08T04:00:00Z", attendance: 30,
    layout: "THEATRE", required_facilities: ["Projector"], wheelchair_access_required: false, accessibility_notes: "" };
  requestVenue(9, input); listEventBookings(9); removeVenueSession(9, 11);
  expect(request).toHaveBeenNthCalledWith(1, "/api/events/9/venue-bookings/", { method: "POST", body: input });
  expect(request).toHaveBeenNthCalledWith(2, "/api/events/9/venue-bookings/");
  expect(request).toHaveBeenNthCalledWith(3, "/api/events/9/venue-sessions/11/remove/", { method: "POST", body: {} });
});
it("SCRUM-87 client contract: withdrawing one revision includes its expected status and explicit release", () => {
  withdrawVenue(9, { id: 2, status: "APPROVED" } as VenueBooking, true);
  expect(request).toHaveBeenCalledWith("/api/events/9/venue-bookings/2/withdraw/", {
    method: "POST", body: { expected_status: "APPROVED", confirm_release: true },
  });
});
it("SCRUM-87 client contract: staff decisions target one booking; inbox filters are encoded", () => {
  listBookingInbox(); listBookingInbox("PENDING&other=1"); approveBooking(2); rejectBooking(3, "Room unavailable");
  expect(request).toHaveBeenNthCalledWith(1, "/api/venue-bookings/");
  expect(request).toHaveBeenNthCalledWith(2, "/api/venue-bookings/?status=PENDING%26other%3D1");
  expect(request).toHaveBeenNthCalledWith(3, "/api/venue-bookings/2/approve/", { method: "POST", body: {} });
  expect(request).toHaveBeenNthCalledWith(4, "/api/venue-bookings/3/reject/", { method: "POST", body: { reason: "Room unavailable" } });
});

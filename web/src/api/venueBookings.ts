import { request } from "./client";
import type { VenueBooking } from "../types";

export const withdrawVenue = (eventId: number, booking: VenueBooking, confirmRelease: boolean) =>
  request<{ detail: string; booking: VenueBooking }>(
    `/api/events/${eventId}/venue-bookings/${booking.id}/withdraw/`,
    { method: "POST", body: { expected_status: booking.status, confirm_release: confirmRelease } },
  );

/** SCRUM-11 - what the coordinator sends when requesting a venue. */
export interface VenueRequestInput {
  session_id?: number;
  session_name?: string;
  session_kind?: "MAIN" | "BREAKOUT";
  replaces_id?: number;
  venue: number | null;
  starts_at: string | null;
  ends_at: string | null;
  attendance: number | null;
  layout: string;
  required_facilities: string[];
  wheelchair_access_required: boolean;
  accessibility_notes: string;
}

export const listEventBookings = (eventId: number) =>
  request<VenueBooking[]>(`/api/events/${eventId}/venue-bookings/`);

export const requestVenue = (eventId: number, input: VenueRequestInput) =>
  request<{ detail: string; booking: VenueBooking }>(`/api/events/${eventId}/venue-bookings/`, {
    method: "POST",
    body: input,
  });

/** Venue Staff's booking-request inbox; pass a status such as "PENDING" to filter. */
export const listBookingInbox = (status?: string) =>
  request<VenueBooking[]>(
    status ? `/api/venue-bookings/?status=${encodeURIComponent(status)}` : "/api/venue-bookings/",
  );

/** SCRUM-72 - Venue Staff approve a Pending booking request. */
export const approveBooking = (bookingId: number) =>
  request<{ detail: string; booking: VenueBooking }>(`/api/venue-bookings/${bookingId}/approve/`, {
    method: "POST",
    body: {},
  });

/** SCRUM-72 - Venue Staff reject a Pending booking request; a reason is required. */
export const rejectBooking = (bookingId: number, reason: string) =>
  request<{ detail: string; booking: VenueBooking }>(`/api/venue-bookings/${bookingId}/reject/`, {
    method: "POST",
    body: { reason },
  });

export const removeVenueSession = (eventId: number, sessionId: number) =>
  request(`/api/events/${eventId}/venue-sessions/${sessionId}/remove/`, { method: "POST", body: {} });

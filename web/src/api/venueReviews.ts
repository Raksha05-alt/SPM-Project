import { request } from "./client";

/** SCRUM-66 - an approved venue flagged for review after the event changed. */
export interface VenueReview {
  id: number;
  booking: number;
  venue: string;
  booking_status: string;
  reasons: { requirement: string; message: string }[];
  changed_fields: string[];
  source: string;
  raised_by_name: string | null;
  raised_at: string;
  is_open: boolean;
  resolved_at: string | null;
  resolution: string;
}

export const getVenueReviews = (eventId: number) =>
  request<{ event: number; open: VenueReview[]; history: VenueReview[] }>(
    `/api/events/${eventId}/venue-reviews/`,
  );

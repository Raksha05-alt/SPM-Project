import { request } from "./client";
export interface CancellationPreview {
  event: number; event_name: string; version: string;
  venue_bookings: { id: number; venue__name: string; status: string; starts_at: string; ends_at: string }[];
  equipment_reservations: { id: number; request__equipment_type__name: string; quantity: number; starts_at: string; ends_at: string }[];
}
export const getCancellationPreview = (id: number) => request<CancellationPreview>(`/api/events/${id}/cancellation-preview/`);
export const cancelEvent = (id: number, version: string, reason: string) => request<{ event: number; status: "CANCELLED"; released_equipment_reservations: number; withdrawn_venue_bookings: number }>(`/api/events/${id}/cancel/`, { method: "POST", body: { expected_version: version, confirm_cancel: true, reason } });

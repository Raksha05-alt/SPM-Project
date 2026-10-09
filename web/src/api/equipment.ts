import { request } from "./client";

export type EquipmentRequestStatus = "REQUESTED" | "RESERVED" | "UNAVAILABLE" | "WITHDRAWN";

export interface EquipmentType {
  id: number;
  name: string;
  category: string;
  description: string;
  total_quantity: number;
  out_of_service_quantity: number;
  out_of_service_reason: string;
  expected_return: string | null;
}

export interface AvailabilityRow {
  equipment: number;
  name: string;
  category: string;
  total_quantity: number;
  out_of_service_quantity: number;
  out_of_service_reason: string;
  expected_return: string | null;
  reserved_for_other_events: number;
  available_quantity: number;
  status: string;
  requested_quantity?: number;
  reserved_for_this_event?: number;
  shortfall?: number;
}

export interface Availability {
  event: number | null;
  start: string;
  end: string;
  results: AvailabilityRow[];
}

export interface HoldingEvent {
  event: number;
  event_name: string;
  event_status: string;
  start: string;
  end: string;
  quantity: number;
  coordinator_name: string | null;
}

export interface EquipmentHolders {
  equipment: number;
  name: string;
  out_of_service_quantity: number;
  out_of_service_reason: string;
  expected_return: string | null;
  holding_events: HoldingEvent[];
}

export interface EquipmentReservation {
  id: number;
  quantity: number;
  start: string;
  end: string;
  reserved_by_name: string | null;
  reserved_at: string;
  released_at: string | null;
  released_by_name: string | null;
  release_reason: string;
}

export interface EquipmentRequestChange {
  description: string;
  changed_by_name: string | null;
  changed_at: string;
}

export interface EquipmentRequest {
  id: number;
  event: number;
  event_name: string;
  equipment_type: number;
  equipment_name: string;
  quantity: number;
  technical_requirements: string;
  status: EquipmentRequestStatus;
  status_display: string;
  reserved_quantity: number;
  requested_by_name: string | null;
  created_at: string;
  withdrawn_by_name: string | null;
  withdrawn_at: string | null;
  unavailable_reason: string;
  review_required: boolean;
  review_reason: string;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_outcome: string;
  reservations: EquipmentReservation[];
  changes: EquipmentRequestChange[];
}

/** SCRUM-12 - an event's own period, or a chosen start and end (ISO with timezone). */
export type AvailabilityPeriod = { event: number } | { start: string; end: string };

function periodQuery(period: AvailabilityPeriod) {
  const params =
    "event" in period
      ? new URLSearchParams({ event: String(period.event) })
      : new URLSearchParams({ start: period.start, end: period.end });
  return params.toString();
}

export const listEquipment = () => request<EquipmentType[]>("/api/equipment/");

export const fetchAvailability = (period: AvailabilityPeriod) =>
  request<Availability>(`/api/equipment/availability/?${periodQuery(period)}`);

export const fetchHolders = (equipmentId: number, period: AvailabilityPeriod) =>
  request<EquipmentHolders>(`/api/equipment/${equipmentId}/holders/?${periodQuery(period)}`);

export const listEquipmentRequests = (eventId?: number) =>
  request<EquipmentRequest[]>(
    eventId === undefined
      ? "/api/equipment-requests/"
      : `/api/equipment-requests/?event=${eventId}`,
  );

export const reserveEquipment = (requestId: number) =>
  request<EquipmentRequest>(`/api/equipment-requests/${requestId}/reserve/`, { method: "POST" });

export const markUnavailable = (requestId: number, reason: string) =>
  request<EquipmentRequest>(`/api/equipment-requests/${requestId}/mark-unavailable/`, {
    method: "POST",
    body: { reason },
  });

export const reviewEquipmentRequest = (requestId: number, accommodated: boolean, note: string) =>
  request<EquipmentRequest>(`/api/equipment-requests/${requestId}/review/`, {
    method: "POST",
    body: { accommodated, note },
  });

export const releaseReservation = (reservationId: number, reason: string) =>
  request<EquipmentRequest>(`/api/equipment-reservations/${reservationId}/release/`, {
    method: "POST",
    body: { reason },
  });

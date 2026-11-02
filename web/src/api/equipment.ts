import { request } from "./client";
import type {
  EquipmentAvailability,
  EquipmentRequest,
  EquipmentType,
  TechnicalEvent,
} from "../types";

/** SCRUM-74 - what the coordinator sends when requesting equipment. */
export interface EquipmentRequestInput {
  equipment_type: number | null;
  quantity: number | null;
  technical_requirements: string;
}

export const listEquipmentTypes = () => request<EquipmentType[]>("/api/equipment/types/");

export const listEventEquipment = (eventId: number) =>
  request<EquipmentRequest[]>(`/api/events/${eventId}/equipment-requests/`);

export const requestEquipment = (eventId: number, input: EquipmentRequestInput) =>
  request<{ detail: string; request: EquipmentRequest }>(
    `/api/events/${eventId}/equipment-requests/`,
    { method: "POST", body: input },
  );

/** SCRUM-74 AC3 - Technical Support's list of events with requested equipment. */
export const listEquipmentInbox = () => request<TechnicalEvent[]>("/api/equipment/requests/");

/** SCRUM-12 - availability for the event's period, or a chosen one. */
export function getEquipmentAvailability(
  eventId: number,
  period?: { starts_at: string; ends_at: string },
) {
  const query = period ? `?${new URLSearchParams(period).toString()}` : "";
  return request<EquipmentAvailability>(
    `/api/events/${eventId}/equipment-availability/${query}`,
  );
}

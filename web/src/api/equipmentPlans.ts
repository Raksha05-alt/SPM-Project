import { request } from "./client";
import type { EquipmentRequest, EventStatus } from "../types";

export interface EquipmentReservation {
  id: number; request: number; quantity: number;
  starts_at: string; ends_at: string; status: "ACTIVE" | "RELEASED";
  reserved_by_name: string; reserved_at: string;
  released_by_name: string | null; released_at: string | null; release_reason: string;
}
export interface EquipmentPlan {
  event: { id: number; name: string; status: EventStatus; starts_at: string | null; ends_at: string | null };
  revision: number; requests: EquipmentRequest[]; reservations: EquipmentReservation[];
  technical_approval: { id: number; revision: number; no_equipment_required: boolean; notes: string; approved_by_name: string; approved_at: string } | null;
}
export const listEquipmentPlans = () => request<{ id: number; name: string }[]>("/api/equipment/plans/");
export const getEquipmentPlan = (id: number) => request<EquipmentPlan>(`/api/events/${id}/equipment-plan/`);
export const reserveEquipment = (id: number, revision: number) => request<EquipmentPlan>(`/api/equipment/requests/${id}/reserve/`, { method: "POST", body: { expected_revision: revision } });
export const approveNoEquipment = (id: number, revision: number, notes: string) => request<EquipmentPlan>(`/api/events/${id}/approve-no-equipment/`, { method: "POST", body: { expected_revision: revision, acknowledged: true, notes } });
export const releaseEquipment = (id: number, revision: number, reason: string) => request<EquipmentPlan>(`/api/equipment/reservations/${id}/release/`, { method: "POST", body: { expected_revision: revision, reason } });

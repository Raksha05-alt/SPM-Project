import { request } from "./client";
import type { Venue } from "../types";

export interface BlockInput { reason: string; starts_at: string; ends_at: string }
export interface VenueBlock extends BlockInput { id: number }
export interface BlockHistory extends VenueBlock {
  block_id: number; action: string; actor_name: string; created_at: string;
}
export interface Availability {
  venue_id: number; status: string; available: boolean; timezone: string;
  starts_at: string; ends_at: string; blocks: VenueBlock[];
}
const base = (id: number) => `/api/venues/${id}`;
export const getAvailability = (id: number, start: string, end: string) =>
  request<Availability>(`${base(id)}/availability/?${new URLSearchParams({ starts_at: start, ends_at: end })}`);
export const getBlocks = (id: number) => request<VenueBlock[]>(`${base(id)}/blocks/`);
export const findAvailableVenues = (start: string, end: string) =>
  request<Venue[]>(`/api/venues/available/?${new URLSearchParams({ starts_at: start, ends_at: end })}`);
export const getBlockHistory = (id: number) => request<BlockHistory[]>(`${base(id)}/blocks/history/`);
export const saveBlock = (id: number, block: BlockInput, blockId?: number) =>
  request<VenueBlock>(`${base(id)}/blocks/${blockId ? `${blockId}/` : ""}`, {
    method: blockId ? "PATCH" : "POST", body: block,
  });
export const removeBlock = (id: number, blockId: number) =>
  request<void>(`${base(id)}/blocks/${blockId}/`, { method: "DELETE" });

import { request } from "./client";

/** Week 7 clarification - room layouts are a catalogue maintained by Venue Staff. */
export interface LayoutType {
  id: number;
  code: string;
  name: string;
  description: string;
  is_active: boolean;
}

export interface LayoutInput {
  code?: string;
  name: string;
  description: string;
  is_active?: boolean;
}

export const listLayouts = () => request<LayoutType[]>("/api/layouts/");

export const createLayout = (input: LayoutInput) =>
  request<LayoutType>("/api/layouts/", { method: "POST", body: input });

export const updateLayout = (id: number, input: Partial<LayoutInput>) =>
  request<LayoutType>(`/api/layouts/${id}/`, { method: "PATCH", body: input });

export const deleteLayout = (id: number) =>
  request<void>(`/api/layouts/${id}/`, { method: "DELETE" });

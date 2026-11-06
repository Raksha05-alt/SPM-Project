import { request } from "./client";
import type { LayoutType } from "../types";

/** SCRUM-91 - the room layout catalogue that Venue Staff maintain. */
export type LayoutInput = Partial<Pick<LayoutType, "code" | "name" | "description">>;

const path = (code: string, suffix = "") => `/api/layouts/${encodeURIComponent(code)}/${suffix}`;

export const listLayouts = () => request<LayoutType[]>("/api/layouts/");

export const createLayout = (input: LayoutInput) =>
  request<LayoutType>("/api/layouts/", { method: "POST", body: input });

export const updateLayout = (code: string, input: LayoutInput) =>
  request<LayoutType>(path(code), { method: "PATCH", body: input });

export const deleteLayout = (code: string) => request<void>(path(code), { method: "DELETE" });

export const retireLayout = (code: string) =>
  request<LayoutType>(path(code, "retire/"), { method: "POST" });

export const reinstateLayout = (code: string) =>
  request<LayoutType>(path(code, "reinstate/"), { method: "POST" });

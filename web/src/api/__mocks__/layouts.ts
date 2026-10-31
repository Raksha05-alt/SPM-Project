import { vi } from "vitest";
import type { LayoutType } from "../../types";

/** The five layouts the catalogue is seeded with (migration 0006). */
export const SEED_LAYOUTS: LayoutType[] = [
  ["CLASSROOM", "Classroom"],
  ["THEATRE", "Theatre"],
  ["BOARDROOM", "Boardroom"],
  ["BANQUET", "Banquet"],
  ["EXHIBITION", "Exhibition"],
].map(([code, name], index) => ({
  code,
  name,
  description: "",
  is_active: true,
  sort_order: index + 1,
  updated_by_name: null,
  created_at: "2026-10-28T00:00:00Z",
  updated_at: "2026-10-28T00:00:00Z",
}));

export const listLayouts = vi.fn(async () => SEED_LAYOUTS);
export const createLayout = vi.fn();
export const updateLayout = vi.fn();
export const deleteLayout = vi.fn();
export const retireLayout = vi.fn();
export const reinstateLayout = vi.fn();

import { useQuery } from "@tanstack/react-query";
import { listLayouts } from "../../api/layouts";
import type { LayoutType } from "../../types";

/** SCRUM-91 - the live layout catalogue, shared by every form that offers layouts. */
export function useLayouts() {
  const query = useQuery({ queryKey: ["layouts"], queryFn: listLayouts, staleTime: 30_000 });
  return { layouts: query.data ?? [], isLoading: query.isLoading, isError: query.isError };
}

/**
 * Layouts that may be chosen: every active one, plus any retired layout already
 * on the record (AC4 - a retired layout cannot be newly chosen, but existing
 * choices stay visible and editable).
 */
export function selectableLayouts(layouts: LayoutType[], current: string[] = []) {
  return layouts.filter((layout) => layout.is_active || current.includes(layout.code));
}

/** AC2 - the current name for a stored code, wherever it is shown. */
export function layoutName(layouts: LayoutType[], code: string) {
  return layouts.find((layout) => layout.code === code)?.name ?? code;
}

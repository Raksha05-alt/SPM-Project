import { useQuery } from "@tanstack/react-query";
import { listLayouts } from "../api/layouts";

/** The starter layouts, used until the catalogue has loaded (or if it cannot). */
export const FALLBACK_LAYOUTS = [
  { value: "CLASSROOM", label: "Classroom" },
  { value: "THEATRE", label: "Theatre" },
  { value: "BOARDROOM", label: "Boardroom" },
  { value: "BANQUET", label: "Banquet" },
  { value: "EXHIBITION", label: "Exhibition" },
];

/**
 * Week 7 clarification - the layouts on offer come from the Venue Staff's catalogue.
 * Retired layouts are left out of new choices. A value already chosen is kept in
 * the list (labelled with its code) so a form never silently drops it.
 */
export function useLayoutOptions(current?: string) {
  const { data } = useQuery({ queryKey: ["layouts"], queryFn: listLayouts, staleTime: 60_000 });
  const options = data
    ? data.filter((l) => l.is_active).map((l) => ({ value: l.code, label: l.name }))
    : FALLBACK_LAYOUTS;
  if (current && !options.some((o) => o.value === current)) {
    const known = data?.find((l) => l.code === current);
    return [...options, { value: current, label: known?.name ?? current }];
  }
  return options;
}

/** The display name of a layout code. */
export function useLayoutLabel() {
  const { data } = useQuery({ queryKey: ["layouts"], queryFn: listLayouts, staleTime: 60_000 });
  return (code: string) =>
    data?.find((l) => l.code === code)?.name ??
    FALLBACK_LAYOUTS.find((l) => l.value === code)?.label ??
    code;
}

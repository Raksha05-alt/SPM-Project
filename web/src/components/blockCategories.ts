import type { BlockCategory } from "../api/venues";

/** Week 7 change 2 - why a venue is temporarily unavailable. */
export const BLOCK_CATEGORIES: { value: BlockCategory; label: string }[] = [
  { value: "MAINTENANCE", label: "Maintenance" },
  { value: "EQUIPMENT_FAILURE", label: "Equipment failure" },
  { value: "RENOVATION", label: "Renovation" },
  { value: "SAFETY", label: "Safety concern" },
  { value: "INTERNAL", label: "Internal activity" },
  { value: "OTHER", label: "Other operational reason" },
];

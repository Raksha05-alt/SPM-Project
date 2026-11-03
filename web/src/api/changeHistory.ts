import { request } from "./client";

/** SCRUM-60 - one recorded change to an event field. */
export interface FieldChange {
  id: number;
  field: string;
  field_label: string;
  before: unknown;
  after: unknown;
  before_display: string;
  after_display: string;
  /** False for earlier edits whose values were never kept. */
  values_recorded: boolean;
  actor_name: string | null;
  source: string;
  source_label: string;
  changed_at: string;
}

export const getChangeHistory = (eventId: number) =>
  request<{ event: number; changes: FieldChange[] }>(`/api/events/${eventId}/change-history/`);

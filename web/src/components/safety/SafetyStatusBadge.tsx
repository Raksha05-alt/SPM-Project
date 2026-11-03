import type { SafetyStatus } from "../../types";

/** SCRUM-90 - colour and wording for a safety check's status. */
const STYLES: Record<SafetyStatus, string> = {
  PENDING: "bg-amber-100 text-amber-900",
  APPROVED: "bg-emerald-100 text-emerald-900",
  REJECTED: "bg-rose-100 text-rose-900",
  CHANGES_REQUESTED: "bg-orange-100 text-orange-900",
  SUPERSEDED: "bg-slate-200 text-slate-700",
};

export function SafetyStatusBadge({ status, label }: { status: SafetyStatus; label: string }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${STYLES[status]}`}>
      {label}
    </span>
  );
}

export function formatDateTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

/** The person and time behind a decision, e.g. "Sam Safety · 29/10/2026, 10:00:00". */
export function decisionLine(name: string | null, at: string | null) {
  return `${name ?? "Unknown"} · ${formatDateTime(at)}`;
}

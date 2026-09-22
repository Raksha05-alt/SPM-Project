import type { EventStatus } from "../types";

const TONES: Record<EventStatus, string> = {
  DRAFT: "bg-slate-100 text-slate-700 ring-slate-300",
  SUBMITTED: "bg-blue-50 text-blue-800 ring-blue-300",
  UNDER_REVIEW: "bg-amber-50 text-amber-800 ring-amber-300",
  APPROVED: "bg-emerald-50 text-emerald-800 ring-emerald-300",
  PLANNING: "bg-indigo-50 text-indigo-800 ring-indigo-300",
  CONFIRMED: "bg-emerald-100 text-emerald-900 ring-emerald-400",
  COMPLETED: "bg-slate-200 text-slate-800 ring-slate-400",
  CANCELLED: "bg-rose-50 text-rose-800 ring-rose-300",
  REJECTED: "bg-rose-100 text-rose-900 ring-rose-400",
};

export function StatusBadge({
  status,
  label,
  title,
}: {
  status: EventStatus;
  label: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[status]}`}
    >
      {label}
    </span>
  );
}

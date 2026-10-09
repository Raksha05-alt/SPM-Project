import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LAYOUT_OPTIONS,
  approveChangeRequest,
  fetchChangeRequest,
  fetchChangeRequests,
  formatDateTime,
  rejectChangeRequest,
  type ChangeImpact,
  type ChangeRequest,
} from "../../api/planning";
import { inputClass } from "../Field";

const secondary =
  "rounded-md border border-slate-300 bg-white px-3 py-1 text-sm font-medium hover:bg-slate-50 disabled:opacity-50";

function proposals(change: ChangeRequest): string[] {
  const rows: string[] = [];
  if (change.proposed_start) rows.push(`Start: ${formatDateTime(change.proposed_start)}`);
  if (change.proposed_end) rows.push(`End: ${formatDateTime(change.proposed_end)}`);
  if (change.proposed_attendance != null)
    rows.push(`Attendance: ${change.proposed_attendance}`);
  if (change.proposed_layout) {
    const label = LAYOUT_OPTIONS.find((o) => o.value === change.proposed_layout)?.label;
    rows.push(`Layout: ${label ?? change.proposed_layout}`);
  }
  if (change.proposed_accessibility_needs)
    rows.push(`Accessibility needs: ${change.proposed_accessibility_needs}`);
  if (change.proposed_equipment_notes)
    rows.push(`Equipment: ${change.proposed_equipment_notes}`);
  return rows;
}

/** SCRUM-78 - the event's change requests, their impact and the coordinator's decision. */
export function ChangeRequestsPanel({
  eventId,
  canDecide,
}: {
  eventId: number;
  canDecide: boolean;
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["change-requests", eventId],
    queryFn: () => fetchChangeRequests(eventId),
  });
  const [openId, setOpenId] = useState<number | null>(null);

  return (
    <section
      aria-label="Change requests"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <h2 className="mb-3 text-sm font-semibold text-navy-700">Change requests</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading change requests…</p>}
      {isError && (
        <p role="alert" className="text-sm text-rose-800">
          {error.message}
        </p>
      )}
      {data && data.length === 0 && (
        <p className="text-sm text-slate-500">The client has not requested any changes.</p>
      )}
      <ul className="divide-y divide-slate-200 text-sm">
        {data?.map((change) => (
          <li key={change.id} className="py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-medium">
                  {change.description}{" "}
                  <span className="font-normal text-slate-600">· {change.status_display}</span>
                </p>
                <p className="text-xs text-slate-500">
                  {change.requested_by_name ?? "Client"} · {formatDateTime(change.created_at)}
                </p>
                {change.reason && <p className="text-xs">Why: {change.reason}</p>}
                {proposals(change).length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-xs">
                    {proposals(change).map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                )}
                {change.status !== "PENDING" && (
                  <p className="mt-1 text-xs text-slate-600">
                    {change.status_display} by {change.decided_by_name ?? "—"} ·{" "}
                    {formatDateTime(change.decided_at)}: {change.decision_reason}
                  </p>
                )}
              </div>
              {change.status === "PENDING" && openId !== change.id && (
                <button
                  type="button"
                  className={secondary}
                  onClick={() => setOpenId(change.id)}
                  aria-label={`Review impact of ${change.description}`}
                >
                  Review impact
                </button>
              )}
            </div>
            {openId === change.id && (
              <ChangeDetail
                changeId={change.id}
                eventId={eventId}
                canDecide={canDecide}
                onClose={() => setOpenId(null)}
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ImpactView({ impact }: { impact: ChangeImpact }) {
  if (!impact.has_impact) {
    return <p className="text-sm text-slate-600">{impact.message}</p>;
  }
  return (
    <div className="space-y-3 text-xs">
      {impact.changed_fields.length > 0 && (
        <p>Changes the event's {impact.changed_fields.join(", ")}.</p>
      )}
      {impact.venue_bookings.length > 0 && (
        <div>
          <p className="font-semibold">Venue bookings</p>
          <ul className="list-disc pl-5">
            {impact.venue_bookings.map((b) => (
              <li key={b.booking}>
                {b.venue} ({b.status}): {formatDateTime(b.current_start)} →{" "}
                {formatDateTime(b.new_start)}
                {b.potentially_unsuitable && (
                  <span className="ml-1 font-medium text-rose-800">Potentially unsuitable</span>
                )}
                {b.issues.map((issue) => (
                  <span key={issue} className="block text-rose-800">
                    {issue}
                  </span>
                ))}
                {b.conflicts.map((c, i) => (
                  <span key={i} className="block text-rose-800">
                    Conflicts with {c.event_name} ({formatDateTime(c.start)} –{" "}
                    {formatDateTime(c.end)})
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}
      {impact.equipment.length > 0 && (
        <div>
          <p className="font-semibold">Equipment</p>
          <ul className="list-disc pl-5">
            {impact.equipment.map((e) => (
              <li key={e.request}>
                {e.quantity} x {e.equipment} ({e.reserved_quantity} reserved)
                {e.issues.map((issue) => (
                  <span key={issue} className="block text-rose-800">
                    {issue}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}
      {impact.registrations && (
        <div>
          <p className="font-semibold">Registrations</p>
          <p>
            {impact.registrations.registered} registered, {impact.registrations.waitlisted} on
            the waiting list
          </p>
          {impact.registrations.issues.map((issue) => (
            <p key={issue} className="text-rose-800">
              {issue}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function ChangeDetail({
  changeId,
  eventId,
  canDecide,
  onClose,
}: {
  changeId: number;
  eventId: number;
  canDecide: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["change-request", changeId],
    queryFn: () => fetchChangeRequest(changeId),
  });
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);

  const decide = useMutation({
    mutationFn: (approve: boolean) =>
      (approve ? approveChangeRequest : rejectChangeRequest)(changeId, reason.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["change-requests", eventId] });
      void queryClient.invalidateQueries({ queryKey: ["event", eventId] });
      void queryClient.invalidateQueries({ queryKey: ["event-history", eventId] });
      onClose();
    },
  });

  function submit(approve: boolean) {
    // SCRUM-78 AC5 - the API also refuses a decision without a reason.
    if (!reason.trim()) {
      setReasonError("Enter a reason for your decision.");
      return;
    }
    setReasonError(null);
    decide.mutate(approve);
  }

  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-4">
      <h3 className="mb-2 text-sm font-semibold text-navy-700">Impact</h3>
      {detail.isLoading && <p className="text-sm text-slate-500">Assessing the impact…</p>}
      {detail.isError && (
        <p role="alert" className="text-sm text-rose-800">
          {detail.error.message}
        </p>
      )}
      {detail.data?.impact && <ImpactView impact={detail.data.impact} />}

      {canDecide && (
        <div className="mt-4">
          {decide.error && (
            <p role="alert" className="mb-2 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              {decide.error.message}
            </p>
          )}
          <label htmlFor={`decision-reason-${changeId}`} className="mb-1 block text-sm font-medium">
            Reason for your decision
          </label>
          <textarea
            id={`decision-reason-${changeId}`}
            rows={2}
            className={inputClass}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {reasonError && (
            <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
              {reasonError}
            </p>
          )}
          <div className="mt-3 flex justify-end gap-3">
            <button type="button" className={secondary} onClick={onClose}>
              Close
            </button>
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() => submit(false)}
              className="rounded-md border border-rose-300 bg-white px-3 py-1 text-sm font-medium text-rose-800 hover:bg-rose-50 disabled:opacity-50"
            >
              Reject change
            </button>
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() => submit(true)}
              className="rounded-md bg-navy-700 px-3 py-1 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Approve change
            </button>
          </div>
        </div>
      )}
      {!canDecide && (
        <div className="mt-3 flex justify-end">
          <button type="button" className={secondary} onClick={onClose}>
            Close
          </button>
        </div>
      )}
    </div>
  );
}

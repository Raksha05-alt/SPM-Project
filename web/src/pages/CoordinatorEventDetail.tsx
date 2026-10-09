import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { approveEvent, getEvent, rejectEvent, requestClarification } from "../api/events";
import { useAuth } from "../auth/AuthContext";
import { ApprovalNote } from "../components/ApprovalNote";
import { CLARIFIABLE_FIELDS, ClarificationHistory } from "../components/Clarifications";
import { inputClass } from "../components/Field";
import { ChangeHistory } from "../components/planning/ChangeHistory";
import { ChangeRequestsPanel } from "../components/planning/ChangeRequestsPanel";
import { EquipmentPlanner } from "../components/planning/EquipmentPlanner";
import { EventActions } from "../components/planning/EventActions";
import { EventEditPanel } from "../components/planning/EventEditPanel";
import { RegistrationsPanel } from "../components/planning/RegistrationsPanel";
import { VenuePlanner } from "../components/planning/VenuePlanner";
import { RejectionNotice } from "../components/RejectionNotice";
import { StatusBadge } from "../components/StatusBadge";
import type { EventRequest, EventStatus } from "../types";

const LAYOUT_LABELS: Record<string, string> = {
  CLASSROOM: "Classroom",
  THEATRE: "Theatre",
  BOARDROOM: "Boardroom",
  BANQUET: "Banquet",
  EXHIBITION: "Exhibition",
};

/** Statuses a coordinator can approve from; the API enforces the same rule. */
const REVIEWABLE: EventStatus[] = ["SUBMITTED", "UNDER_REVIEW"];

/** Statuses in which venues, equipment and details are planned (SCRUM-61, 11, 74). */
const PLANNABLE: EventStatus[] = ["APPROVED", "PLANNING", "CONFIRMED"];

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 whitespace-pre-line text-sm text-slate-800">{children}</dd>
    </div>
  );
}

export function CoordinatorEventDetail() {
  const { id } = useParams();
  const eventId = Number(id);
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const {
    data: event,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["event", eventId],
    queryFn: () => getEvent(eventId),
  });

  function onDecision(updated: EventRequest) {
    queryClient.setQueryData(["event", eventId], updated);
    void queryClient.invalidateQueries({ queryKey: ["my-events"] });
    void queryClient.invalidateQueries({ queryKey: ["queue"] });
  }

  const approve = useMutation({ mutationFn: approveEvent, onSuccess: onDecision });

  const [showReject, setShowReject] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const reject = useMutation({
    mutationFn: () => rejectEvent(eventId, reason.trim()),
    onSuccess: (updated) => {
      onDecision(updated);
      setShowReject(false);
      setReason("");
    },
  });

  function confirmRejection() {
    // SCRUM-52 AC2 - the API also blocks a rejection without a reason.
    if (!reason.trim()) {
      setReasonError("Enter a reason for the rejection.");
      return;
    }
    setReasonError(null);
    reject.mutate();
  }

  const [showClarify, setShowClarify] = useState(false);
  const [message, setMessage] = useState("");
  const [fields, setFields] = useState<string[]>([]);
  const [messageError, setMessageError] = useState<string | null>(null);
  const clarify = useMutation({
    mutationFn: () => requestClarification(eventId, message.trim(), fields),
    onSuccess: (updated) => {
      onDecision(updated);
      setShowClarify(false);
      setMessage("");
      setFields([]);
    },
  });

  function sendClarification() {
    // SCRUM-49 AC4 - the API also refuses a request that does not say what is needed.
    if (!message.trim()) {
      setMessageError("Say what information is needed.");
      return;
    }
    setMessageError(null);
    clarify.mutate();
  }

  function toggleField(value: string) {
    setFields((current) =>
      current.includes(value) ? current.filter((f) => f !== value) : [...current, value],
    );
  }

  if (isLoading) return <p className="text-slate-500">Loading the event…</p>;
  if (isError || !event) return <p role="alert">We could not load this event.</p>;

  const isAssigned = event.coordinator === user?.id;
  const canApprove = isAssigned && REVIEWABLE.includes(event.status);
  const canClarify = isAssigned && event.status === "SUBMITTED";
  const canReject = canApprove;
  const canPlan = isAssigned && PLANNABLE.includes(event.status);
  const decisionError = approve.error ?? clarify.error ?? reject.error;

  return (
    <div>
      <div className="mb-4 flex gap-4 text-sm">
        <Link to="/coordinator/mine" className="text-navy-700 underline">
          ← My assigned events
        </Link>
        <Link to="/coordinator" className="text-navy-700 underline">
          Incoming requests
        </Link>
      </div>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-navy-700">{event.name}</h1>
          <p className="text-sm text-slate-500">
            {event.organisation_name} · raised by {event.created_by_name}
          </p>
        </div>
        <div className="text-right">
          <StatusBadge
            status={event.status}
            label={event.status_label}
            title={event.status_description}
          />
          <p className="mt-1 text-xs text-slate-500">{event.status_description}</p>
          <ApprovalNote
            approvedBy={event.approved_by_name ?? null}
            approvedAt={event.approved_at ?? null}
          />
        </div>
      </div>

      <RejectionNotice event={event} />

      {decisionError && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {decisionError.message}
        </p>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <dl className="grid gap-6 sm:grid-cols-2">
          <Detail label="Purpose">{event.purpose || "—"}</Detail>
          <Detail label="Expected attendance">{event.expected_attendance ?? "—"}</Detail>
          <Detail label="Preferred start">{formatDateTime(event.preferred_start)}</Detail>
          <Detail label="Preferred end">{formatDateTime(event.preferred_end)}</Detail>
          <Detail label="Required room layout">
            {LAYOUT_LABELS[event.required_layout] ?? "No preference"}
          </Detail>
          <Detail label="Registration required">
            {event.registration_required ? "Yes" : "No"}
          </Detail>
          <div className="sm:col-span-2">
            <Detail label="Description">{event.description || "—"}</Detail>
          </div>
          <div className="sm:col-span-2">
            <Detail label="Accessibility needs">{event.accessibility_needs || "—"}</Detail>
          </div>
          <div className="sm:col-span-2">
            <Detail label="Equipment and technical requirements">
              {event.equipment_notes || "—"}
            </Detail>
          </div>
          <Detail label="Coordinator">
            {event.coordinator_name ?? "Not assigned"}
            {event.coordinator_email && (
              <>
                {" · "}
                <a className="text-navy-700 underline" href={`mailto:${event.coordinator_email}`}>
                  {event.coordinator_email}
                </a>
              </>
            )}
          </Detail>
          <Detail label="Submitted">{formatDateTime(event.submitted_at)}</Detail>
        </dl>
      </section>

      {showClarify && canClarify && (
        <section
          aria-label="Request clarification"
          className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
        >
          <h2 className="mb-3 text-sm font-semibold text-navy-700">Request clarification</h2>
          <label htmlFor="clarification-message" className="mb-1 block text-sm font-medium">
            What do you need from the client?
          </label>
          <textarea
            id="clarification-message"
            rows={3}
            className={inputClass}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
          {messageError && (
            <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
              {messageError}
            </p>
          )}
          <fieldset className="mt-4">
            <legend className="mb-2 text-sm font-medium">Items to review (optional)</legend>
            <div className="grid gap-1 sm:grid-cols-2">
              {CLARIFIABLE_FIELDS.map((f) => (
                <label key={f.value} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={fields.includes(f.value)}
                    onChange={() => toggleField(f.value)}
                  />
                  {f.label}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="mt-4 flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setShowClarify(false)}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={sendClarification}
              disabled={clarify.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Send to client
            </button>
          </div>
        </section>
      )}

      {showReject && canReject && (
        <section
          aria-label="Reject request"
          className="mt-6 rounded-lg border border-rose-200 bg-white p-6"
        >
          <h2 className="mb-3 text-sm font-semibold text-rose-800">Reject request</h2>
          <label htmlFor="rejection-reason" className="mb-1 block text-sm font-medium">
            Why can ConnectSphere not support this request?
          </label>
          <textarea
            id="rejection-reason"
            rows={3}
            className={inputClass}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {reasonError && (
            <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
              {reasonError}
            </p>
          )}
          <p className="mt-2 text-xs text-slate-500">
            The client will see this reason. A rejected request cannot be reopened.
          </p>
          <div className="mt-4 flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setShowReject(false)}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirmRejection}
              disabled={reject.isPending}
              className="rounded-md bg-rose-700 px-4 py-2 text-sm font-medium text-white hover:bg-rose-800 disabled:opacity-50"
            >
              Confirm rejection
            </button>
          </div>
        </section>
      )}

      {(canApprove || canClarify) && (
        <div className="mt-6 flex justify-end gap-3">
          {canReject && !showReject && (
            <button
              type="button"
              onClick={() => setShowReject(true)}
              className="rounded-md border border-rose-300 bg-white px-4 py-2 text-sm font-medium text-rose-800 hover:bg-rose-50"
            >
              Reject request
            </button>
          )}
          {canClarify && !showClarify && (
            <button
              type="button"
              onClick={() => setShowClarify(true)}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
            >
              Request clarification
            </button>
          )}
          {canApprove && (
            <button
              type="button"
              onClick={() => approve.mutate(event.id)}
              disabled={approve.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Approve request
            </button>
          )}
        </div>
      )}

      {isAssigned && <EventActions event={event} />}

      <ClarificationHistory clarifications={event.clarifications ?? []} />

      {canPlan && (
        <>
          <EventEditPanel event={event} />
          <VenuePlanner event={event} />
          <EquipmentPlanner event={event} />
        </>
      )}
      {isAssigned && event.registration_required && <RegistrationsPanel eventId={event.id} />}
      <ChangeRequestsPanel eventId={event.id} canDecide={isAssigned} />
      <ChangeHistory eventId={event.id} />
    </div>
  );
}

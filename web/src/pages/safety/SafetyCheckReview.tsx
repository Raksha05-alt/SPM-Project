import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { decideSafetyCheck, getSafetyCheck } from "../../api/safety";
import { inputClass } from "../../components/Field";
import {
  SafetyStatusBadge,
  decisionLine,
  formatDateTime,
} from "../../components/safety/SafetyStatusBadge";
import type { SafetyDecision, SafetyFacts, SafetyVenueFacts } from "../../types";

const NOT_RECORDED = "Not recorded";

const DECISIONS: { value: SafetyDecision; label: string; hint: string }[] = [
  { value: "APPROVED", label: "Approve", hint: "The event is safe to run as planned." },
  {
    value: "CHANGES_REQUESTED",
    label: "Request changes",
    hint: "Safe once the arrangements are revised.",
  },
  { value: "REJECTED", label: "Reject", hint: "Not safe with these arrangements." },
];

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  // AC2 - missing safety information is named, never left blank.
  const missing = value === null || value === undefined || value === "";
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 whitespace-pre-line text-sm">
        {missing ? <span className="font-medium text-amber-700">{NOT_RECORDED}</span> : value}
      </dd>
    </div>
  );
}

function wheelchair(value: boolean | null) {
  if (value === null) return null;
  return value ? "Yes" : "No";
}

function VenueFacts({ venue }: { venue: SafetyVenueFacts }) {
  const over = venue.booked_attendance > venue.capacity;
  return (
    <article
      aria-label={`Venue ${venue.venue}`}
      className="rounded-lg border border-slate-200 bg-white p-5"
    >
      <h3 className="font-semibold text-navy-700">{venue.venue}</h3>
      <p className="mb-4 text-xs text-slate-500">
        {venue.location || "Location not recorded"} · {formatDateTime(venue.starts_at)} to{" "}
        {formatDateTime(venue.ends_at)}
      </p>
      <dl className="grid gap-4 sm:grid-cols-2">
        <Item
          label="Capacity / booked"
          value={
            <span className={over ? "font-semibold text-rose-700" : undefined}>
              {venue.capacity} / {venue.booked_attendance}
            </span>
          }
        />
        <Item label="Layout" value={venue.layout} />
        <Item label="Wheelchair access" value={wheelchair(venue.wheelchair_access)} />
        <Item label="Accessibility information" value={venue.accessibility_notes} />
        <div className="sm:col-span-2">
          <Item label="Emergency access" value={venue.emergency_access} />
        </div>
        <div className="sm:col-span-2">
          <Item label="Known restrictions" value={venue.known_restrictions} />
        </div>
        {venue.booking_accessibility_notes && (
          <div className="sm:col-span-2">
            <Item label="Booking accessibility notes" value={venue.booking_accessibility_notes} />
          </div>
        )}
      </dl>
    </article>
  );
}

export function SafetyFactsView({ facts }: { facts: SafetyFacts }) {
  return (
    <div className="space-y-6">
      {facts.concerns.length > 0 && (
        <section
          aria-label="Points to check"
          className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
        >
          <h2 className="mb-2 font-semibold">Points to check</h2>
          <ul className="list-disc space-y-1 pl-5">
            {facts.concerns.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs">Drawn from the recorded facts. The decision is yours.</p>
        </section>
      )}

      <section aria-label="Event" className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-4 text-sm font-semibold text-navy-700">Event</h2>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Item label="Expected attendance" value={facts.expected_attendance} />
          <Item label="Required layout" value={facts.required_layout} />
          <Item label="Starts" value={formatDateTime(facts.starts_at)} />
          <Item label="Ends" value={formatDateTime(facts.ends_at)} />
          <div className="sm:col-span-2">
            <Item label="Accessibility requirements" value={facts.accessibility_needs} />
          </div>
        </dl>
      </section>

      <section aria-label="Venues">
        <h2 className="mb-3 text-sm font-semibold text-navy-700">Venues</h2>
        <div className="space-y-4">
          {facts.venues.map((v) => (
            <VenueFacts key={v.booking} venue={v} />
          ))}
        </div>
      </section>

      <section aria-label="Equipment" className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-navy-700">Equipment to be placed</h2>
        {facts.equipment.length === 0 ? (
          <p className="text-sm text-slate-600">
            {facts.technical_approval?.no_equipment_required
              ? "Technical Support confirmed that no equipment is required."
              : "No equipment recorded."}
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-2">Item</th>
                <th className="py-2">Quantity</th>
                <th className="py-2">Technical requirements</th>
              </tr>
            </thead>
            <tbody>
              {facts.equipment.map((e) => (
                <tr key={e.equipment} className="border-t border-slate-100">
                  <td className="py-2">{e.equipment}</td>
                  <td className="py-2">
                    {e.reserved_quantity} of {e.quantity} reserved
                  </td>
                  <td className="py-2">{e.technical_requirements || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {facts.technical_approval && (
          <p className="mt-3 text-xs text-slate-500">
            Technical approval:{" "}
            {decisionLine(facts.technical_approval.approved_by, facts.technical_approval.approved_at)}
          </p>
        )}
      </section>
    </div>
  );
}

/** SCRUM-90 AC2/AC3 - a Safety Officer reviews one check and records a decision. */
export function SafetyCheckReview() {
  const checkId = Number(useParams().id);
  const client = useQueryClient();
  const key = ["safety-check", checkId];
  const { data: check, isLoading, isError } = useQuery({
    queryKey: key,
    queryFn: () => getSafetyCheck(checkId),
    refetchOnWindowFocus: true,
  });

  const [decision, setDecision] = useState<SafetyDecision | null>(null);
  const [comment, setComment] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const submit = useMutation({
    mutationFn: () => decideSafetyCheck(checkId, decision!, comment.trim()),
    onSuccess: (updated) => client.setQueryData(key, updated),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: key });
      void client.invalidateQueries({ queryKey: ["safety-checks"] });
    },
  });

  function record() {
    if (!decision) {
      setFormError("Choose approve, request changes or reject.");
      return;
    }
    // AC3 - the API also refuses a blank comment for these decisions.
    if (decision !== "APPROVED" && !comment.trim()) {
      setFormError("Add a comment saying what is unsafe or what must change.");
      return;
    }
    setFormError(null);
    submit.mutate();
  }

  if (isLoading) return <p className="text-slate-500">Loading the safety check…</p>;
  if (isError || !check) return <p role="alert">We could not load this safety check.</p>;

  const pending = check.status === "PENDING";
  const facts = check.current_facts ?? check.facts;

  return (
    <div>
      <Link to="/safety" className="text-sm text-navy-700 underline">
        ← Safety checks
      </Link>
      <div className="mb-6 mt-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-navy-700">{check.event_name}</h1>
          <p className="text-sm text-slate-500">
            {check.organisation_name} · coordinator {check.coordinator_name ?? "not assigned"} ·
            requested {formatDateTime(check.requested_at)}
          </p>
        </div>
        <SafetyStatusBadge status={check.status} label={check.status_display} />
      </div>

      {check.is_stale && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          The arrangements have changed since this check was requested. It can no longer be
          approved; the coordinator must request a new check.
        </p>
      )}
      {check.request_note && (
        <p className="mb-4 rounded-md bg-slate-50 p-3 text-sm text-slate-700">
          <span className="font-medium">Coordinator's note:</span> {check.request_note}
        </p>
      )}
      {!pending && (
        <p className="mb-4 text-xs text-slate-500">
          Showing the arrangements as they were when the check was requested.
        </p>
      )}

      <SafetyFactsView facts={facts} />

      {!pending && check.decided_at && (
        <section aria-label="Recorded decision" className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-2 text-sm font-semibold text-navy-700">Decision</h2>
          <p className="text-sm">
            {check.status_display} by {decisionLine(check.decided_by_name, check.decided_at)}
          </p>
          {check.comment && <p className="mt-2 whitespace-pre-line text-sm">{check.comment}</p>}
        </section>
      )}
      {check.status === "SUPERSEDED" && (
        <p className="mt-4 text-sm text-slate-600">
          Superseded {formatDateTime(check.superseded_at)}: {check.superseded_reason}
        </p>
      )}

      {pending && !check.is_stale && (
        <section aria-label="Your decision" className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-navy-700">Your decision</h2>
          <fieldset className="mb-4 space-y-2">
            <legend className="sr-only">Decision</legend>
            {DECISIONS.map((d) => (
              <label key={d.value} className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="decision"
                  value={d.value}
                  checked={decision === d.value}
                  onChange={() => setDecision(d.value)}
                  className="mt-1"
                />
                <span>
                  <span className="font-medium">{d.label}</span>
                  <span className="block text-xs text-slate-500">{d.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <label htmlFor="safety-comment" className="mb-1 block text-sm font-medium">
            Comment {decision && decision !== "APPROVED" ? "(required)" : "(optional)"}
          </label>
          <textarea
            id="safety-comment"
            rows={3}
            className={inputClass}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          {(formError || submit.error) && (
            <p role="alert" className="mt-2 text-sm font-medium text-rose-700">
              {formError ?? submit.error?.message}
            </p>
          )}
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={record}
              disabled={submit.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Record decision
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

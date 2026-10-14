import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  decideSafetyCheck,
  getSafetyCheck,
  type SafetyDecision,
  type SafetyFacts,
} from "../../api/safety";
import { inputClass } from "../../components/Field";

function when(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

function Facts({ facts }: { facts: SafetyFacts }) {
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-xs uppercase text-slate-500">Expected attendance</dt>
          <dd>{facts.expected_attendance ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-slate-500">Event period</dt>
          <dd>
            {when(facts.start)} – {when(facts.end)}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-slate-500">Required layout</dt>
          <dd>{facts.required_layout || "No preference"}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-slate-500">Accessibility needs</dt>
          <dd>{facts.accessibility_needs || "—"}</dd>
        </div>
      </dl>

      <div>
        <h3 className="mb-2 font-semibold text-navy-700">Venues</h3>
        <ul className="space-y-2">
          {facts.venues.map((v) => (
            <li key={v.booking} className="rounded-md border border-slate-200 p-3">
              <p className="font-medium">
                {v.venue}
                {v.session ? ` · ${v.session}` : ""}
              </p>
              <p className="text-xs text-slate-600">
                {v.location} · capacity {v.capacity} · {v.attendance} booked
                {v.layout ? ` · ${v.layout}` : ""}
              </p>
              <p className="text-xs text-slate-600">
                Occupied {when(v.occupied_from)} – {when(v.occupied_until)}
              </p>
              <p className="text-xs text-slate-600">
                Step-free access:{" "}
                {v.wheelchair_access === null ? "not recorded" : v.wheelchair_access ? "yes" : "no"}
                {v.accessibility_notes ? ` · ${v.accessibility_notes}` : ""}
              </p>
              <p className="mt-1 text-xs">
                <span className="font-medium">Emergency access and restrictions: </span>
                {v.safety_notes || "Not recorded"}
              </p>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="mb-2 font-semibold text-navy-700">Equipment to be placed</h3>
        {facts.equipment.length === 0 ? (
          <p className="text-slate-500">No equipment.</p>
        ) : (
          <ul className="list-disc pl-5">
            {facts.equipment.map((e, i) => (
              <li key={i}>
                {e.quantity} x {e.equipment}
                {e.technical_requirements ? ` – ${e.technical_requirements}` : ""}
              </li>
            ))}
          </ul>
        )}
      </div>

      {facts.concerns.length > 0 && (
        <div aria-label="Concerns" className="rounded-md bg-amber-50 p-3 text-amber-900">
          <p className="font-medium">The recorded facts suggest looking at:</p>
          <ul className="mt-1 list-disc pl-5">
            {facts.concerns.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * Week 7 change 6 - the Safety Officer reviews the planned event and approves it,
 * rejects the safety arrangement or requests changes, with a comment.
 */
export function SafetyCheckDetail() {
  const { id } = useParams();
  const checkId = Number(id);
  const queryClient = useQueryClient();
  const { data: check, isLoading, isError } = useQuery({
    queryKey: ["safety-check", checkId],
    queryFn: () => getSafetyCheck(checkId),
  });
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const decide = useMutation({
    mutationFn: (decision: SafetyDecision) => decideSafetyCheck(checkId, decision, comment.trim()),
    onSuccess: (updated) => {
      queryClient.setQueryData(["safety-check", checkId], updated);
      void queryClient.invalidateQueries({ queryKey: ["safety-checks"] });
    },
  });

  function submit(decision: SafetyDecision) {
    if (decision !== "APPROVED" && !comment.trim()) {
      setError("Say what is unsafe or what must change.");
      return;
    }
    setError(null);
    decide.mutate(decision);
  }

  if (isLoading) return <p className="text-slate-500">Loading the safety check…</p>;
  if (isError || !check) return <p role="alert">We could not load this safety check.</p>;
  const pending = check.status === "PENDING";

  return (
    <div>
      <Link to="/safety" className="mb-4 inline-block text-sm text-navy-700 underline">
        ← Safety checks
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-navy-700">{check.event_name}</h1>
          <p className="text-sm text-slate-500">
            {check.organisation_name} · coordinator {check.coordinator_name ?? "—"}
          </p>
        </div>
        <p className="text-sm font-medium">{check.status_display}</p>
      </div>

      {check.request_note && (
        <p className="mb-4 rounded-md bg-blue-50 p-3 text-sm text-blue-900">
          From the coordinator: {check.request_note}
        </p>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h2 className="mb-3 text-sm font-semibold text-navy-700">
          {pending ? "Current arrangements" : "Arrangements when the check was requested"}
        </h2>
        <Facts facts={check.current_facts ?? check.facts} />
      </section>

      {pending ? (
        <section
          aria-label="Decision"
          className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
        >
          <h2 className="mb-3 text-sm font-semibold text-navy-700">Your decision</h2>
          <label htmlFor="safety-comment" className="mb-1 block text-sm font-medium">
            Comment (required to reject or request changes)
          </label>
          <textarea
            id="safety-comment"
            rows={3}
            className={inputClass}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          {(error || decide.error) && (
            <p role="alert" className="mt-2 text-sm font-medium text-rose-700">
              {error ?? decide.error?.message}
            </p>
          )}
          <div className="mt-4 flex flex-wrap justify-end gap-3">
            <button
              type="button"
              onClick={() => submit("REJECTED")}
              disabled={decide.isPending}
              className="rounded-md border border-rose-300 bg-white px-4 py-2 text-sm font-medium text-rose-800 hover:bg-rose-50 disabled:opacity-50"
            >
              Reject safety arrangement
            </button>
            <button
              type="button"
              onClick={() => submit("CHANGES_REQUESTED")}
              disabled={decide.isPending}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
            >
              Request changes
            </button>
            <button
              type="button"
              onClick={() => submit("APPROVED")}
              disabled={decide.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Approve
            </button>
          </div>
        </section>
      ) : (
        <section className="mt-6 rounded-lg border border-slate-200 bg-white p-6 text-sm">
          <p>
            {check.status_display}
            {check.decided_by_name ? ` by ${check.decided_by_name}` : ""} ·{" "}
            {when(check.decided_at ?? check.superseded_at)}
          </p>
          {check.comment && <p className="mt-1">Comment: {check.comment}</p>}
          {check.superseded_reason && (
            <p className="mt-1 text-slate-600">No longer applies: {check.superseded_reason}</p>
          )}
        </section>
      )}
    </div>
  );
}

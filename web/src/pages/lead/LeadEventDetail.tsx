import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import { assignCoordinator, getLeadEvent, listCoordinators, type CoordinatorChoice, type LeadEvent } from "../../api/leadAssignments";
import { useAuth } from "../../auth/AuthContext";
import { Field, inputClass } from "../../components/Field";
import { StatusBadge } from "../../components/StatusBadge";

export function LeadEventDetail() {
  const eventId = Number(useParams().id);
  const { user } = useAuth();
  const client = useQueryClient();
  const key = ["lead-event", user?.id, eventId];
  const [notice, setNotice] = useState("");
  const event = useQuery({ queryKey: key, queryFn: () => getLeadEvent(eventId), refetchOnWindowFocus: true });
  const choices = useQuery({
    queryKey: ["lead-coordinators", user?.id], queryFn: listCoordinators,
    enabled: event.data?.can_assign === true, refetchOnWindowFocus: true,
  });
  const assignment = useMutation({
    mutationFn: ({ coordinatorId, revision }: { coordinatorId: number; revision: number }) => assignCoordinator(eventId, coordinatorId, revision),
    onSuccess: updated => { client.setQueryData(key, updated); setNotice("Coordinator assignment saved."); },
    onError: error => setNotice(error instanceof ApiError ? error.message : "We could not confirm the save. Check the latest assignment below before trying again."),
    onSettled: () => Promise.all([
      client.invalidateQueries({ queryKey: key }),
      client.invalidateQueries({ queryKey: ["lead-events"] }),
      client.invalidateQueries({ queryKey: ["event", eventId] }),
      client.invalidateQueries({ queryKey: ["queue"] }),
      client.invalidateQueries({ queryKey: ["my-events"] }),
      client.invalidateQueries({ queryKey: ["notifications"] }),
    ]),
  });

  if (event.isPending) return <p>Loading event…</p>;
  if (event.isError) return <p role="alert">We could not load this event. <button className="underline" onClick={() => void event.refetch()}>Try again</button></p>;
  const data = event.data;
  return <div>
    <Link to="/lead" className="text-navy-700 underline">Back to coordinator assignments</Link>
    <h1 className="mb-2 mt-4 text-2xl font-semibold text-navy-700">{data.name}</h1>
    <StatusBadge status={data.status} label={data.status_label} />
    <p className="mt-4">{data.organisation_name} · {data.purpose}</p>
    <p className="text-sm text-slate-600">{data.preferred_start ? new Date(data.preferred_start).toLocaleString("en-SG") : "Start not recorded"} to {data.preferred_end ? new Date(data.preferred_end).toLocaleString("en-SG") : "end not recorded"} · {data.expected_attendance ?? "Unrecorded"} attending</p>
    <section aria-label="Current assignment" className="my-5 rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="font-semibold">Current assignment</h2>
      <p>Coordinator: {data.coordinator_name ?? "Unassigned"}{data.coordinator_email ? ` (${data.coordinator_email})` : ""}</p>
      <p>Supervising Lead: {data.supervising_lead_name ?? "Not recorded"}</p>
    </section>
    {notice && <p role={assignment.isError ? "alert" : "status"} className="my-4">{notice}</p>}
    {!data.can_assign ? <p>Assignments cannot be changed for completed or cancelled events.</p> : choices.isPending ? <p>Loading coordinators…</p> : choices.isError ? <p role="alert">We could not load coordinators. <button className="underline" onClick={() => void choices.refetch()}>Try again</button></p> : (
      <AssignmentForm key={data.assignment_revision} event={data} choices={choices.data} busy={assignment.isPending || event.isFetching} onAssign={coordinatorId => { setNotice(""); assignment.reset(); assignment.mutate({ coordinatorId, revision: data.assignment_revision }); }} />
    )}
    <section aria-label="Assignment history" className="mt-8">
      <h2 className="mb-3 text-lg font-semibold">Assignment history</h2>
      {data.assignment_history.length === 0 ? <p>No assignment changes have been recorded.</p> : <ol className="space-y-3">{data.assignment_history.map(change => <li key={change.id} className="rounded border border-slate-200 bg-white p-4">
        <p>{change.previous_coordinator_name ?? "Unassigned"} → {change.coordinator_name}</p>
        <p className="text-sm text-slate-600">By {change.assigned_by_name} · <time dateTime={change.assigned_at}>{new Date(change.assigned_at).toLocaleString("en-SG")}</time></p>
      </li>)}</ol>}
    </section>
  </div>;
}

function AssignmentForm({ event, choices, busy, onAssign }: { event: LeadEvent; choices: CoordinatorChoice[]; busy: boolean; onAssign: (id: number) => void }) {
  const [selected, setSelected] = useState("");
  if (choices.length === 0) return <p>No active coordinator accounts are available.</p>;
  return <form aria-label="Coordinator assignment" onSubmit={e => { e.preventDefault(); if (selected && Number(selected) !== event.coordinator) onAssign(Number(selected)); }} className="rounded-lg border border-slate-200 bg-white p-5">
    <Field label="Event Coordinator" htmlFor="coordinator-choice" hint="Availability is shown for reference; the Lead chooses the coordinator.">
      <select id="coordinator-choice" className={inputClass} value={selected} disabled={busy} required onChange={e => setSelected(e.target.value)}>
        <option value="">Select a coordinator</option>
        {choices.map(choice => <option key={choice.id} value={choice.id}>{choice.name} ({choice.email}){choice.coordinator_available ? "" : " — marked unavailable"}</option>)}
      </select>
    </Field>
    <button type="submit" disabled={busy || !selected || Number(selected) === event.coordinator} className="rounded-md bg-navy-700 px-4 py-2 text-white disabled:opacity-50">{busy ? "Saving…" : event.coordinator ? "Reassign coordinator" : "Assign coordinator"}</button>
  </form>;
}

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listAssignments, listUnassignedEvents } from "../../api/leadAssignments";
import { useAuth } from "../../auth/AuthContext";
import { StatusBadge } from "../../components/StatusBadge";

export function LeadDashboard() {
  const { user } = useAuth();
  const [tab, setTab] = useState<"unassigned" | "assignments">("unassigned");
  const [onlyMine, setOnlyMine] = useState(false);
  const [active, setActive] = useState(true);
  const events = useQuery({
    queryKey: ["lead-events", user?.id, tab, onlyMine, active],
    queryFn: () => tab === "unassigned" ? listUnassignedEvents() : listAssignments(onlyMine, active),
    refetchOnWindowFocus: true,
  });

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold text-navy-700">Coordinator assignments</h1>
      <p className="mb-5 text-slate-600">Allocate submitted requests and review who is responsible for each event.</p>
      <div className="mb-5 flex gap-4">
        <button type="button" aria-pressed={tab === "unassigned"} onClick={() => setTab("unassigned")} className="text-navy-700 underline">Unassigned requests</button>
        <button type="button" aria-pressed={tab === "assignments"} onClick={() => setTab("assignments")} className="text-navy-700 underline">Assignments</button>
      </div>
      {tab === "assignments" && <div className="mb-5 flex flex-wrap gap-5">
        <label><input type="checkbox" checked={onlyMine} onChange={e => setOnlyMine(e.target.checked)} /> Only events I supervise</label>
        <label><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} /> Active events only</label>
      </div>}
      {events.isPending ? <p>Loading events…</p> : events.isError ? <p role="alert">We could not load assignments. <button type="button" className="underline" onClick={() => void events.refetch()}>Try again</button></p> : events.data.length === 0 ? (
        <p>{tab === "unassigned" ? "No unassigned requests." : "No events match these filters."}</p>
      ) : <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50"><tr>{["Event", "Client", "Preferred start", "Attending", "Status", "Coordinator", "Supervising Lead"].map(label => <th key={label} className="p-3">{label}</th>)}</tr></thead>
          <tbody className="divide-y divide-slate-200">{events.data.map(event => <tr key={event.id}>
            <td className="p-3"><Link className="text-navy-700 underline" to={`/lead/events/${event.id}`}>{event.name}</Link></td>
            <td className="p-3">{event.organisation_name}</td>
            <td className="p-3">{event.preferred_start ? new Date(event.preferred_start).toLocaleString("en-SG") : "Not recorded"}</td>
            <td className="p-3">{event.expected_attendance ?? "Not recorded"}</td>
            <td className="p-3"><StatusBadge status={event.status} label={event.status_label} /></td>
            <td className="p-3">{event.coordinator_name ?? "Unassigned"}</td>
            <td className="p-3">{event.supervising_lead_name ?? "Not recorded"}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </div>
  );
}

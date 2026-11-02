import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { approveNoEquipment, getEquipmentPlan, listEquipmentPlans, reserveEquipment } from "../api/equipmentPlans";
import { useAuth } from "../auth/AuthContext";
import { inputClass } from "../components/Field";

const when = (value: string | null) => value ? new Date(value).toLocaleString("en-SG") : "Not set";

/** SCRUM-16/77: current plan, staff actions and retained reservation evidence. */
export function EquipmentPlanPage() {
  const { id } = useParams();
  const eventId = Number(id);
  const navigate = useNavigate();
  const { user } = useAuth();
  const isTech = user?.role === "TECH_SUPPORT";
  const client = useQueryClient();
  const [notes, setNotes] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [validation, setValidation] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const events = useQuery({ queryKey: ["equipment-plans"], queryFn: listEquipmentPlans, enabled: !id && isTech });
  const plan = useQuery({ queryKey: ["equipment-plan", eventId], queryFn: () => getEquipmentPlan(eventId), enabled: Boolean(id), refetchOnWindowFocus: "always" });
  const refresh = async () => {
    await Promise.all(["equipment-plan", "equipment-inbox", "equipment-availability", "event", "notifications"].map((key) => client.invalidateQueries({ queryKey: [key] })));
  };
  const reserve = useMutation({
    mutationFn: (requestId: number) => reserveEquipment(requestId, plan.data!.revision),
    onSuccess: () => setNotice("Equipment reserved. The coordinator has been notified."),
    onSettled: refresh,
  });
  const approve = useMutation({
    mutationFn: () => approveNoEquipment(eventId, plan.data!.revision, notes.trim()),
    onSuccess: () => setNotice("Technical review recorded: no equipment required."),
    onSettled: refresh,
  });
  const data = plan.data;
  const open = data && ["APPROVED", "PLANNING", "CONFIRMED"].includes(data.event.status) && data.event.ends_at && new Date(data.event.ends_at).getTime() > Date.now();
  const pending = reserve.isPending || approve.isPending;
  const error = reserve.error ?? approve.error;

  if (!id) return <div>
    <h1 className="mb-4 text-2xl font-semibold text-navy-700">Equipment plans</h1>
    <p className="mb-4">Choose an event to reserve its requested equipment or review a plan needing no equipment.</p>
    {events.isLoading && <p>Loading events…</p>}
    {events.error && <p role="alert">We could not load the equipment plans.</p>}
    {events.data?.length === 0 && <p>No events are awaiting technical arrangements.</p>}
    {events.data && events.data.length > 0 && <label>Event<select className={inputClass} defaultValue="" onChange={(e) => { if (e.target.value) navigate(`/equipment/plans/${e.target.value}`); }}>
      <option value="">Choose an event…</option>
      {events.data.map((event) => <option key={event.id} value={event.id}>{event.name}</option>)}
    </select></label>}
  </div>;
  if (plan.isLoading) return <p>Loading equipment plan…</p>;
  if (plan.error || !data) return <p role="alert">We could not load this equipment plan. Check that you still have access.</p>;

  return <div>
    <h1 className="mb-2 text-2xl font-semibold text-navy-700">Equipment plan: {data.event.name}</h1>
    <p className="mb-4">{when(data.event.starts_at)} – {when(data.event.ends_at)} · {data.event.status}</p>
    <div className="mb-4 flex gap-4 text-sm">
      {isTech ? <Link className="underline" to="/equipment">Equipment requests</Link> : <Link className="underline" to={`/coordinator/events/${eventId}`}>Back to event</Link>}
      {isTech && <Link className="underline" to="/equipment/plans">All equipment plans</Link>}
      {data.requests.length > 0 && <Link className="underline" to={`/equipment/availability/${eventId}`}>Check availability</Link>}
      <button className="underline" disabled={plan.isFetching || pending} onClick={() => { void refresh(); }}>Refresh plan</button>
    </div>
    {notice && <p role="status" className="mb-4 text-emerald-800">{notice}</p>}
    {error && <p role="alert" className="mb-4 text-rose-800">{error.message}</p>}
    <p className="mb-4 text-sm">{data.technical_approval ? `Technical arrangements approved by ${data.technical_approval.approved_by_name} on ${when(data.technical_approval.approved_at)}.` : "Technical arrangements are awaiting approval."}</p>
    {isTech && <p className="mb-4 text-sm">Reserving the last outstanding item records technical approval for this plan. Changes require a new Safety check.</p>}
    {data.requests.filter((item) => item.status !== "WITHDRAWN").map((item) => <section key={item.id} aria-label={item.equipment_type_name} className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="font-semibold">{item.quantity} × {item.equipment_type_name}</h2>
      <p>{item.technical_requirements || "No additional technical requirements."}</p>
      <p>{item.status_label}</p>
      {isTech && open && item.status === "REQUESTED" && <button disabled={pending} className="mt-2 rounded bg-navy-700 px-4 py-2 text-white disabled:opacity-50" onClick={() => { setNotice(null); reserve.mutate(item.id); }}>Reserve {item.quantity} × {item.equipment_type_name}</button>}
    </section>)}
    {data.requests.every((item) => item.status === "WITHDRAWN") && <section aria-label="No equipment review" className="rounded-lg border bg-white p-4">
      <p>No equipment is currently requested.</p>
      {isTech && open && !data.technical_approval && <form onSubmit={(e) => {
        e.preventDefault();
        if (!acknowledged || !notes.trim()) { setValidation("Confirm that no equipment is needed and enter your review notes."); return; }
        setValidation(null); approve.mutate();
      }}>
        <label className="my-3 block"><input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} /> I have checked that this event needs no equipment.</label>
        <label>Technical review notes<textarea className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
        {validation && <p role="alert">{validation}</p>}
        <button disabled={pending} className="mt-2 rounded bg-navy-700 px-4 py-2 text-white">Approve no equipment required</button>
      </form>}
    </section>}
    <section aria-label="Reservation history" className="mt-6">
      <h2 className="mb-2 font-semibold">Reservation history</h2>
      {data.reservations.length === 0 && <p>No reservations recorded.</p>}
      {data.reservations.map((row) => <div key={row.id} className="mb-3 rounded border p-3">
        <p>Reservation #{row.id}: {row.quantity} units · {row.status}</p>
        <p>{when(row.starts_at)} – {when(row.ends_at)}</p>
        <p>Reserved by {row.reserved_by_name} on {when(row.reserved_at)}</p>
        {row.released_at && <p>Released by {row.released_by_name} on {when(row.released_at)}: {row.release_reason}</p>}
      </div>)}
    </section>
  </div>;
}

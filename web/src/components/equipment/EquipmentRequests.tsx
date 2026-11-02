import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import { listEquipmentTypes, listEventEquipment, requestEquipment } from "../../api/equipment";
import type { EventRequest } from "../../types";
import { Field, inputClass } from "../Field";

/** Statuses in which equipment can be requested; the API enforces the same rule. */
const OPEN_TO_REQUESTS = ["APPROVED", "PLANNING"];

const EMPTY = { equipment_type: "", quantity: "1", technical_requirements: "" };

/** One message per field from a 400, or a general message for anything else. */
export function describeEquipmentRefusal(error: unknown): {
  detail: string;
  fields: Record<string, string>;
} {
  if (!(error instanceof ApiError)) return { detail: "We could not send the request.", fields: {} };
  if (error.status !== 400) return { detail: error.message, fields: {} };
  const body = (error.body ?? {}) as Record<string, unknown>;
  const fields = Object.fromEntries(
    Object.entries(body)
      .filter(([key]) => key !== "detail")
      .map(([key, value]) => [key, Array.isArray(value) ? String(value[0]) : String(value)]),
  );
  return { detail: error.message, fields };
}

/** SCRUM-74 - the assigned coordinator records the equipment an event requires. */
export function EquipmentRequests({ event }: { event: EventRequest }) {
  const queryClient = useQueryClient();
  const requests = useQuery({
    queryKey: ["equipment-requests", event.id],
    queryFn: () => listEventEquipment(event.id),
  });
  const canRequest = OPEN_TO_REQUESTS.includes(event.status);
  const types = useQuery({
    queryKey: ["equipment-types"],
    queryFn: listEquipmentTypes,
    enabled: canRequest,
  });
  const [form, setForm] = useState(EMPTY);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const set = (key: keyof typeof form, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const send = useMutation({
    mutationFn: () =>
      requestEquipment(event.id, {
        equipment_type: form.equipment_type ? Number(form.equipment_type) : null,
        quantity: form.quantity === "" ? null : Number(form.quantity),
        technical_requirements: form.technical_requirements,
      }),
    onSuccess: (result) => {
      setConfirmation(result.detail);
      setForm(EMPTY);
      void queryClient.invalidateQueries({ queryKey: ["equipment-requests", event.id] });
      // The first request on an Approved event moves it to Planning.
      void queryClient.invalidateQueries({ queryKey: ["event", event.id] });
    },
  });
  const refusal = send.error ? describeEquipmentRefusal(send.error) : null;
  const generalRefusal = refusal && Object.keys(refusal.fields).length === 0;

  return (
    <section
      aria-label="Equipment requests"
      className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
    >
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-navy-700">Equipment requests</h2>
        <Link to={`/equipment/plans/${event.id}`} className="text-sm text-navy-700 underline">Equipment plan and reservations</Link>
        <Link to={`/equipment/availability/${event.id}`} className="text-sm text-navy-700 underline">
          Check availability
        </Link>
      </div>

      {requests.isError && <p role="alert">We could not load this event's equipment requests.</p>}
      {(requests.data ?? []).length === 0 && !requests.isLoading && !requests.isError && (
        <p className="mb-4 text-sm text-slate-500">No equipment has been requested yet.</p>
      )}
      {(requests.data ?? []).length > 0 && (
        <table className="mb-4 w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="py-2">Equipment</th>
              <th className="py-2">Quantity</th>
              <th className="py-2">Technical requirements</th>
              <th className="py-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {requests.data!.map((r) => (
              <tr key={r.id}>
                <td className="py-2 font-medium text-navy-700">{r.equipment_type_name}</td>
                <td className="py-2">{r.quantity}</td>
                <td className="py-2 whitespace-pre-line">{r.technical_requirements || "—"}</td>
                <td className="py-2">
                  <span className="font-medium">{r.status_label}</span>
                  {/* AC4 - who requested it and when. */}
                  <span className="block text-xs text-slate-500">
                    by {r.requested_by_name ?? "Deleted user"} on{" "}
                    {new Date(r.requested_at).toLocaleString("en-SG")}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!canRequest ? (
        <p className="text-sm text-slate-500">
          Equipment can be requested once this event has been approved.
        </p>
      ) : (
        <form
          aria-label="Request equipment"
          onSubmit={(e) => {
            e.preventDefault();
            setConfirmation(null);
            send.mutate();
          }}
        >
          {confirmation && (
            <p role="status" className="mb-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
              {confirmation}
            </p>
          )}
          {generalRefusal && (
            <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              {refusal.detail}
            </p>
          )}
          {refusal?.fields.event && (
            <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
              {refusal.fields.event}
            </p>
          )}
          <div className="grid gap-x-6 sm:grid-cols-2">
            <Field
              label="Equipment"
              htmlFor="equipment-type"
              error={refusal?.fields.equipment_type}
            >
              <select
                id="equipment-type"
                className={inputClass}
                value={form.equipment_type}
                onChange={(e) => set("equipment_type", e.target.value)}
              >
                <option value="">Choose equipment</option>
                {(types.data ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Quantity" htmlFor="equipment-quantity" error={refusal?.fields.quantity}>
              <input
                id="equipment-quantity"
                type="number"
                className={inputClass}
                value={form.quantity}
                onChange={(e) => set("quantity", e.target.value)}
              />
            </Field>
          </div>
          <Field
            label="Technical requirements"
            htmlFor="equipment-requirements"
            hint="Connections, placement, power or anything Technical Support should know"
            error={refusal?.fields.technical_requirements}
          >
            <textarea
              id="equipment-requirements"
              className={inputClass}
              value={form.technical_requirements}
              onChange={(e) => set("technical_requirements", e.target.value)}
            />
          </Field>
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={send.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
            >
              Send request to Technical Support
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

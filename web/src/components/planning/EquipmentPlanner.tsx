import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import {
  amendEquipmentRequest,
  createEquipmentRequest,
  fetchEquipmentAvailability,
  fetchEquipmentRequests,
  fieldErrorsOf,
  formatDateTime,
  listEquipmentTypes,
  withdrawEquipmentRequest,
  type EquipmentRequest,
} from "../../api/planning";
import type { EventRequest } from "../../types";
import { Field, inputClass } from "../Field";

const secondary =
  "rounded-md border border-slate-300 bg-white px-3 py-1 text-sm font-medium hover:bg-slate-50 disabled:opacity-50";
const primary =
  "rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50";
const card = "mt-6 rounded-lg border border-slate-200 bg-white p-6";

/** SCRUM-74 AC2 / SCRUM-75 - the quantity is a whole number of at least one. */
function quantityError(value: string) {
  const n = Number(value);
  if (!value.trim() || !Number.isInteger(n) || n < 1) return "The quantity must be at least 1.";
  return null;
}

function ErrorBox({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="mb-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
      {error.message}
    </p>
  );
}

/** SCRUM-74 record, SCRUM-75 amend/withdraw and SCRUM-12 availability of equipment. */
export function EquipmentPlanner({ event }: { event: EventRequest }) {
  const queryClient = useQueryClient();
  const requests = useQuery({
    queryKey: ["equipment-requests", event.id],
    queryFn: () => fetchEquipmentRequests(event.id),
  });
  const availability = useQuery({
    queryKey: ["equipment-availability", event.id],
    queryFn: () => fetchEquipmentAvailability(event.id),
    enabled: Boolean(event.preferred_start && event.preferred_end),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["equipment-requests", event.id] });
    void queryClient.invalidateQueries({ queryKey: ["equipment-availability", event.id] });
  }

  return (
    <div>
      <section aria-label="Equipment availability" className={card}>
        <h2 className="mb-3 text-sm font-semibold text-navy-700">Equipment availability</h2>
        {!(event.preferred_start && event.preferred_end) && (
          <p className="text-sm text-slate-500">The event has no date and time yet.</p>
        )}
        <ErrorBox error={availability.error} />
        {availability.data && (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-2">Equipment</th>
                <th className="py-2">Available</th>
                <th className="py-2">Requested</th>
                <th className="py-2">Reserved</th>
                <th className="py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {availability.data.results.map((row) => (
                <tr key={row.equipment}>
                  <td className="py-2">{row.name}</td>
                  <td className="py-2">{row.available_quantity}</td>
                  <td className="py-2">{row.requested_quantity ?? 0}</td>
                  <td className="py-2">{row.reserved_for_this_event ?? 0}</td>
                  <td className={`py-2 ${row.shortfall ? "font-medium text-rose-800" : ""}`}>
                    {row.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section aria-label="Equipment requests" className={card}>
        <h2 className="mb-3 text-sm font-semibold text-navy-700">Equipment requests</h2>
        <ErrorBox error={requests.error} />
        {requests.data && requests.data.length === 0 && (
          <p className="text-sm text-slate-500">No equipment has been requested yet.</p>
        )}
        <ul className="divide-y divide-slate-200 text-sm">
          {requests.data?.map((item) => (
            <RequestRow key={item.id} item={item} onChange={refresh} />
          ))}
        </ul>
        <AddRequest eventId={event.id} onAdded={refresh} />
      </section>
    </div>
  );
}

function RequestRow({ item, onChange }: { item: EquipmentRequest; onChange: () => void }) {
  const [amending, setAmending] = useState(false);
  const [quantity, setQuantity] = useState(String(item.quantity));
  const [requirements, setRequirements] = useState(item.technical_requirements);
  const [error, setError] = useState<string | null>(null);

  const amend = useMutation({
    mutationFn: () =>
      amendEquipmentRequest(item.id, {
        quantity: Number(quantity),
        technical_requirements: requirements,
      }),
    onSuccess: () => {
      setAmending(false);
      onChange();
    },
  });
  const withdraw = useMutation({
    mutationFn: () => withdrawEquipmentRequest(item.id),
    onSuccess: onChange,
  });

  function save() {
    const problem = quantityError(quantity);
    setError(problem);
    if (!problem) amend.mutate();
  }

  const active = item.status !== "WITHDRAWN";
  const amendFieldErrors = amend.error instanceof ApiError ? fieldErrorsOf(amend.error.body) : {};

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {item.quantity} x {item.equipment_name}{" "}
            <span className="font-normal text-slate-600">· {item.status_display}</span>
          </p>
          <p className="text-xs text-slate-500">
            Reserved {item.reserved_quantity} of {item.quantity}
            {item.technical_requirements ? ` · ${item.technical_requirements}` : ""}
          </p>
          {item.unavailable_reason && (
            <p className="text-xs text-rose-800">Unavailable: {item.unavailable_reason}</p>
          )}
          {item.review_required && (
            <p className="text-xs text-amber-900">Needs review: {item.review_reason}</p>
          )}
        </div>
        {active && !amending && (
          <div className="flex gap-2">
            <button
              type="button"
              className={secondary}
              onClick={() => setAmending(true)}
              aria-label={`Amend ${item.equipment_name}`}
            >
              Amend
            </button>
            <button
              type="button"
              className={secondary}
              disabled={withdraw.isPending}
              onClick={() => withdraw.mutate()}
              aria-label={`Withdraw ${item.equipment_name}`}
            >
              Withdraw
            </button>
          </div>
        )}
      </div>

      <div className="mt-2">
        <ErrorBox error={withdraw.error} />
        {amend.error && Object.keys(amendFieldErrors).length === 0 && (
          <ErrorBox error={amend.error} />
        )}
      </div>

      {amending && (
        <div className="mt-2 grid gap-x-4 sm:grid-cols-2">
          <Field
            label="Quantity"
            htmlFor={`amend-quantity-${item.id}`}
            error={error ?? amendFieldErrors.quantity}
          >
            <input
              id={`amend-quantity-${item.id}`}
              type="number"
              min={1}
              className={inputClass}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </Field>
          <Field
            label="Technical requirements"
            htmlFor={`amend-requirements-${item.id}`}
            error={amendFieldErrors.technical_requirements}
          >
            <input
              id={`amend-requirements-${item.id}`}
              className={inputClass}
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
            />
          </Field>
          <div className="flex gap-2 sm:col-span-2">
            <button type="button" className={secondary} onClick={() => setAmending(false)}>
              Discard
            </button>
            <button type="button" className={primary} disabled={amend.isPending} onClick={save}>
              Save amendment
            </button>
          </div>
        </div>
      )}

      {item.changes.length > 0 && (
        <details className="mt-2 text-xs text-slate-600">
          <summary className="cursor-pointer">Change history</summary>
          <ul className="mt-1 list-disc pl-5">
            {item.changes.map((c, i) => (
              <li key={i}>
                {c.description} – {c.changed_by_name ?? "System"}, {formatDateTime(c.changed_at)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function AddRequest({ eventId, onAdded }: { eventId: number; onAdded: () => void }) {
  const types = useQuery({ queryKey: ["equipment-types"], queryFn: listEquipmentTypes });
  const [equipmentType, setEquipmentType] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [requirements, setRequirements] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const create = useMutation({
    mutationFn: () =>
      createEquipmentRequest({
        event: eventId,
        equipment_type: Number(equipmentType),
        quantity: Number(quantity),
        technical_requirements: requirements,
      }),
    onSuccess: () => {
      setEquipmentType("");
      setQuantity("1");
      setRequirements("");
      onAdded();
    },
    onError: (error) => {
      if (error instanceof ApiError) setErrors(fieldErrorsOf(error.body));
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!equipmentType) found.equipment_type = "Choose the equipment type.";
    const problem = quantityError(quantity);
    if (problem) found.quantity = problem;
    setErrors(found);
    if (Object.keys(found).length === 0) create.mutate();
  }

  return (
    <form onSubmit={submit} noValidate className="mt-4 border-t border-slate-200 pt-4">
      <h3 className="mb-3 text-sm font-semibold text-navy-700">Add equipment</h3>
      {create.error && Object.keys(errors).length === 0 && <ErrorBox error={create.error} />}
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="Equipment type" htmlFor="equipment-type" error={errors.equipment_type}>
          <select
            id="equipment-type"
            className={inputClass}
            value={equipmentType}
            onChange={(e) => setEquipmentType(e.target.value)}
          >
            <option value="">Choose equipment</option>
            {types.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Quantity" htmlFor="equipment-quantity" error={errors.quantity}>
          <input
            id="equipment-quantity"
            type="number"
            min={1}
            className={inputClass}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </Field>
      </div>
      <Field
        label="Technical requirements"
        htmlFor="equipment-requirements"
        error={errors.technical_requirements}
      >
        <input
          id="equipment-requirements"
          className={inputClass}
          value={requirements}
          onChange={(e) => setRequirements(e.target.value)}
        />
      </Field>
      <div className="flex justify-end">
        <button type="submit" disabled={create.isPending} className={primary}>
          Add equipment request
        </button>
      </div>
    </form>
  );
}

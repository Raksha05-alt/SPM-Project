import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import {
  listEquipmentRequests,
  markUnavailable,
  releaseReservation,
  reserveEquipment,
  reviewEquipmentRequest,
  type EquipmentRequest,
  type EquipmentReservation,
} from "../../api/equipment";
import { inputClass } from "../../components/Field";

const QUERY_KEY = ["equipment-requests"];

const primaryButton =
  "rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50";
const secondaryButton =
  "rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50";

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("en-SG") : "—";
}

/** The API's refusal, with the available quantity when it reports one (SCRUM-16). */
function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null;
  const available =
    error instanceof ApiError
      ? (error.body as { available_quantity?: number } | null)?.available_quantity
      : undefined;
  return (
    <p role="alert" className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
      {error.message}
      {available !== undefined && <> Available quantity: {available}.</>}
    </p>
  );
}

/** A required-text form shared by mark unavailable, release and cannot accommodate. */
function ReasonForm({
  id,
  label,
  submitLabel,
  emptyError,
  pending,
  onSubmit,
  onCancel,
}: {
  id: string;
  label: string;
  submitLabel: string;
  emptyError: string;
  pending: boolean;
  onSubmit: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit() {
    if (!text.trim()) {
      setError(emptyError);
      return;
    }
    setError(null);
    onSubmit(text.trim());
  }

  return (
    <div className="mt-3">
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
        {label}
      </label>
      <textarea
        id={id}
        rows={2}
        className={inputClass}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {error && (
        <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
          {error}
        </p>
      )}
      <div className="mt-2 flex justify-end gap-3">
        <button type="button" onClick={onCancel} className={secondaryButton}>
          Cancel
        </button>
        <button type="button" onClick={submit} disabled={pending} className={primaryButton}>
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

function Reservation({
  reservation,
  onReleased,
}: {
  reservation: EquipmentReservation;
  onReleased: (updated: EquipmentRequest) => void;
}) {
  const [releasing, setReleasing] = useState(false);
  const release = useMutation({
    mutationFn: (reason: string) => releaseReservation(reservation.id, reason),
    onSuccess: (updated) => {
      setReleasing(false);
      onReleased(updated);
    },
  });

  const period = `${formatDateTime(reservation.start)} – ${formatDateTime(reservation.end)}`;

  if (reservation.released_at) {
    // SCRUM-77 AC2 - who released it, when and why.
    return (
      <li className="text-sm text-slate-500">
        {reservation.quantity} reserved for {period} · released by{" "}
        {reservation.released_by_name ?? "the system"} on {formatDateTime(reservation.released_at)}:{" "}
        {reservation.release_reason}
      </li>
    );
  }

  return (
    <li className="text-sm text-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          {reservation.quantity} reserved for {period} by {reservation.reserved_by_name ?? "—"} on{" "}
          {formatDateTime(reservation.reserved_at)}
        </span>
        {!releasing && (
          <button type="button" onClick={() => setReleasing(true)} className={secondaryButton}>
            Release reservation
          </button>
        )}
      </div>
      {releasing && (
        <ReasonForm
          id={`release-reason-${reservation.id}`}
          label="Reason for releasing"
          submitLabel="Confirm release"
          emptyError="Enter a reason for releasing this reservation."
          pending={release.isPending}
          onSubmit={(reason) => release.mutate(reason)}
          onCancel={() => setReleasing(false)}
        />
      )}
      <ErrorMessage error={release.error} />
    </li>
  );
}

function RequestItem({
  item,
  onUpdated,
}: {
  item: EquipmentRequest;
  onUpdated: (updated: EquipmentRequest) => void;
}) {
  const [markingUnavailable, setMarkingUnavailable] = useState(false);
  const [declining, setDeclining] = useState(false);

  const reserve = useMutation({
    mutationFn: () => reserveEquipment(item.id),
    onSuccess: onUpdated,
  });
  const unavailable = useMutation({
    mutationFn: (reason: string) => markUnavailable(item.id, reason),
    onSuccess: (updated) => {
      setMarkingUnavailable(false);
      onUpdated(updated);
    },
  });
  const review = useMutation({
    mutationFn: ({ accommodated, note }: { accommodated: boolean; note: string }) =>
      reviewEquipmentRequest(item.id, accommodated, note),
    onSuccess: (updated) => {
      setDeclining(false);
      onUpdated(updated);
    },
  });

  const outstanding = item.quantity - item.reserved_quantity;
  const canReserve = item.status !== "WITHDRAWN" && outstanding > 0;
  const canMarkUnavailable = item.status === "REQUESTED";
  const error = reserve.error ?? unavailable.error ?? review.error;

  return (
    <li
      aria-label={`${item.equipment_name} for ${item.event_name}`}
      className="rounded-md border border-slate-200 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-medium text-slate-800">
            {item.quantity} × {item.equipment_name}
          </h3>
          <p className="mt-1 whitespace-pre-line text-sm text-slate-600">
            {item.technical_requirements || "No technical requirements given."}
          </p>
        </div>
        <div className="text-right text-sm">
          <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700">
            {item.status_display}
          </span>
          <p className="mt-1 text-xs text-slate-500">
            {item.reserved_quantity} of {item.quantity} reserved
          </p>
        </div>
      </div>

      {item.status === "UNAVAILABLE" && item.unavailable_reason && (
        <p className="mt-2 text-sm text-slate-600">Unavailable: {item.unavailable_reason}</p>
      )}

      {item.review_required && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
          <p className="font-medium text-slate-800">Review needed: {item.review_reason}</p>
          {!declining && (
            <div className="mt-2 flex gap-3">
              <button
                type="button"
                onClick={() => review.mutate({ accommodated: true, note: "" })}
                disabled={review.isPending}
                className={primaryButton}
              >
                Accommodate
              </button>
              <button type="button" onClick={() => setDeclining(true)} className={secondaryButton}>
                Cannot accommodate
              </button>
            </div>
          )}
          {declining && (
            <ReasonForm
              id={`review-note-${item.id}`}
              label="Why can the change not be accommodated?"
              submitLabel="Record outcome"
              emptyError="Explain why the change cannot be accommodated."
              pending={review.isPending}
              onSubmit={(note) => review.mutate({ accommodated: false, note })}
              onCancel={() => setDeclining(false)}
            />
          )}
        </div>
      )}
      {!item.review_required && item.review_outcome && (
        <p className="mt-2 text-sm text-slate-600">
          Review: {item.review_outcome}
          {item.reviewed_by_name && <> ({item.reviewed_by_name})</>}
        </p>
      )}

      {item.reservations.length > 0 && (
        <ul className="mt-3 space-y-2">
          {item.reservations.map((r) => (
            <Reservation key={r.id} reservation={r} onReleased={onUpdated} />
          ))}
        </ul>
      )}

      {markingUnavailable && (
        <ReasonForm
          id={`unavailable-reason-${item.id}`}
          label="Why is this equipment unavailable?"
          submitLabel="Confirm unavailable"
          emptyError="Enter the reason the equipment is unavailable."
          pending={unavailable.isPending}
          onSubmit={(reason) => unavailable.mutate(reason)}
          onCancel={() => setMarkingUnavailable(false)}
        />
      )}

      {(canReserve || canMarkUnavailable) && !markingUnavailable && (
        <div className="mt-3 flex justify-end gap-3">
          {canMarkUnavailable && (
            <button
              type="button"
              onClick={() => setMarkingUnavailable(true)}
              className={secondaryButton}
            >
              Mark unavailable
            </button>
          )}
          {canReserve && (
            <button
              type="button"
              onClick={() => reserve.mutate()}
              disabled={reserve.isPending}
              className={primaryButton}
            >
              Reserve {outstanding}
            </button>
          )}
        </div>
      )}

      <ErrorMessage error={error} />
    </li>
  );
}

export function EquipmentNav() {
  return (
    <nav className="mb-4 flex gap-4 text-sm">
      <Link to="/equipment" className="text-navy-700 underline">
        Equipment requests
      </Link>
      <Link to="/equipment/availability" className="text-navy-700 underline">
        Availability
      </Link>
    </nav>
  );
}

export function EquipmentRequests() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => listEquipmentRequests(),
  });

  function onUpdated(updated: EquipmentRequest) {
    queryClient.setQueryData<EquipmentRequest[]>(QUERY_KEY, (current) =>
      current?.map((r) => (r.id === updated.id ? updated : r)),
    );
  }

  // SCRUM-74 AC3 - every requested item, grouped by event.
  const byEvent = new Map<number, { name: string; items: EquipmentRequest[] }>();
  for (const item of data ?? []) {
    const group = byEvent.get(item.event) ?? { name: item.event_name, items: [] };
    group.items.push(item);
    byEvent.set(item.event, group);
  }

  return (
    <div>
      <EquipmentNav />
      <h1 className="mb-6 text-2xl font-semibold text-navy-700">Equipment requests</h1>

      {isLoading && <p className="text-slate-500">Loading equipment requests…</p>}
      {isError && <p role="alert">We could not load the equipment requests.</p>}
      {data && data.length === 0 && (
        <p className="text-slate-500">No equipment has been requested yet.</p>
      )}

      {[...byEvent.entries()].map(([eventId, group]) => (
        <section
          key={eventId}
          aria-label={group.name}
          className="mb-6 rounded-lg border border-slate-200 bg-white p-6"
        >
          <h2 className="mb-3 text-lg font-semibold text-navy-700">{group.name}</h2>
          <ul className="space-y-3">
            {group.items.map((item) => (
              <RequestItem key={item.id} item={item} onUpdated={onUpdated} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

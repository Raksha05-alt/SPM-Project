import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  listMyRegistrations,
  withdrawRegistration,
  type MyRegistration,
  type WithdrawalSummary,
} from "../api/attendee";

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("en-SG") : "Date to be confirmed";
}

/** SCRUM-21 AC4 / SCRUM-14 - my registrations, and withdrawing from one. */
export function MyRegistrations() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["my-registrations"],
    queryFn: listMyRegistrations,
  });

  if (isLoading) return <p className="text-slate-500">Loading your registrations…</p>;
  if (isError) return <p role="alert">We could not load your registrations.</p>;

  const registrations = data ?? [];

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold text-navy-700">My registrations</h1>
        <Link to="/events" className="text-sm text-navy-700 underline">
          Browse events
        </Link>
      </div>
      {registrations.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          You have not registered for any events yet.
        </p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {registrations.map((registration) => (
            <RegistrationRow key={registration.id} registration={registration} />
          ))}
        </ul>
      )}
    </div>
  );
}

function RegistrationRow({ registration }: { registration: MyRegistration }) {
  const queryClient = useQueryClient();
  const [summary, setSummary] = useState<WithdrawalSummary | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);

  const withdraw = useMutation({
    mutationFn: (confirm: boolean) => withdrawRegistration(registration.id, confirm),
    onSuccess: () => {
      setSummary(null);
      void queryClient.invalidateQueries({ queryKey: ["my-registrations"] });
      void queryClient.invalidateQueries({ queryKey: ["attendee-events"] });
    },
    onError: (error) => {
      // The API answers the first request with a summary to confirm.
      const body = error instanceof ApiError ? (error.body as { summary?: WithdrawalSummary }) : null;
      if (body?.summary) {
        setSummary(body.summary);
        return;
      }
      setSummary(null);
      setRefusal(error instanceof Error ? error.message : "Something went wrong.");
    },
  });

  function start() {
    setRefusal(null);
    withdraw.mutate(false);
  }

  return (
    <li className="px-4 py-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-medium text-navy-700">{registration.event_name}</h2>
          <p className="mt-1 text-sm text-slate-600">
            {formatDateTime(registration.event_start)}
            {registration.event_end ? ` to ${formatDateTime(registration.event_end)}` : ""}
          </p>
          <p className="mt-1 text-sm text-slate-600">
            {registration.venues.length
              ? registration.venues
                  .map((v) => `${v.name}${v.location ? `, ${v.location}` : ""}`)
                  .join("; ")
              : "Venue to be confirmed"}
          </p>
        </div>
        <span className="whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">
          {registration.status_display}
        </span>
      </div>

      {refusal && (
        <p role="alert" className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {refusal}
        </p>
      )}

      {summary ? (
        <section
          aria-label="Confirm withdrawal"
          className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
        >
          <p className="font-medium">Withdraw from {summary.event}?</p>
          <p className="mt-1">
            {formatDateTime(summary.start)}
            {summary.end ? ` to ${formatDateTime(summary.end)}` : ""} · Current status:{" "}
            {summary.status}
          </p>
          <div className="mt-3 flex gap-3">
            <button
              type="button"
              disabled={withdraw.isPending}
              onClick={() => withdraw.mutate(true)}
              className="rounded-md bg-rose-700 px-4 py-2 text-sm font-medium text-white hover:bg-rose-600"
            >
              Confirm withdrawal
            </button>
            <button
              type="button"
              onClick={() => setSummary(null)}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
            >
              Keep my place
            </button>
          </div>
        </section>
      ) : (
        registration.status !== "WITHDRAWN" && (
          <button
            type="button"
            disabled={withdraw.isPending}
            onClick={start}
            className="mt-3 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
          >
            Withdraw
          </button>
        )
      )}
    </li>
  );
}

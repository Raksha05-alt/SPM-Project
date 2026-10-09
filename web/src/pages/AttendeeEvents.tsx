import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  joinWaitlist,
  listOpenEvents,
  registerForEvent,
  type AttendeeEventRow,
  type RegistrationInput,
} from "../api/attendee";
import { useAuth } from "../auth/AuthContext";
import { Field, inputClass } from "../components/Field";
import { StatusBadge } from "../components/StatusBadge";

export function AttendeeEvents() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["attendee-events"],
    queryFn: listOpenEvents,
  });

  if (isLoading) return <p className="text-slate-500">Loading events…</p>;
  if (isError) return <p role="alert">We could not load the events.</p>;

  const events = data ?? [];

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="mb-1 text-2xl font-semibold text-navy-700">Events</h1>
          <p className="text-sm text-slate-500">Confirmed and recently concluded events.</p>
        </div>
        <Link to="/events/mine" className="text-sm text-navy-700 underline">
          My registrations
        </Link>
      </div>

      {events.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-slate-500">
          There are no confirmed events to show right now.
        </p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {events.map((event) => (
            <EventRow key={event.id} event={event} />
          ))}
        </ul>
      )}
    </div>
  );
}

type Mode = "register" | "waitlist";

function EventRow({ event }: { event: AttendeeEventRow }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode | null>(null);
  const [form, setForm] = useState<RegistrationInput>({
    full_name: user ? `${user.first_name} ${user.last_name}`.trim() : "",
    email: user?.email ?? "",
    accessibility_needs: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refusal, setRefusal] = useState<string | null>(null);
  // SCRUM-19 - the API may say the event filled up and offer its waiting list.
  const [waitlistOffered, setWaitlistOffered] = useState(event.waitlist_offered);
  const [done, setDone] = useState<string | null>(null);

  const mine = event.my_registration;
  const canRegister =
    event.registration_required && !event.registration_message && !mine && event.places_left !== 0;
  const canJoinWaitlist = waitlistOffered && !mine;

  const send = useMutation({
    mutationFn: (how: Mode) =>
      how === "register" ? registerForEvent(event.id, form) : joinWaitlist(event.id, form),
    onSuccess: (registration) => {
      setMode(null);
      setDone(`Your status: ${registration.status_display}.`);
      void queryClient.invalidateQueries({ queryKey: ["attendee-events"] });
      void queryClient.invalidateQueries({ queryKey: ["my-registrations"] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 400 && error.body) {
        const next: Record<string, string> = {};
        for (const [key, value] of Object.entries(error.body as Record<string, unknown>)) {
          if (key === "detail") continue;
          next[key] = Array.isArray(value) ? String(value[0]) : String(value);
        }
        setErrors(next);
        if ("detail" in (error.body as object)) setRefusal(error.message);
        return;
      }
      if (error instanceof ApiError) {
        const body = error.body as { waitlist_offered?: boolean } | null;
        if (body?.waitlist_offered) setWaitlistOffered(true);
      }
      setRefusal(error instanceof Error ? error.message : "Something went wrong.");
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setRefusal(null);
    // SCRUM-21 AC2 - name and email are required; the API checks them too.
    const next: Record<string, string> = {};
    if (!form.full_name.trim()) next.full_name = "Enter your full name.";
    if (!form.email.trim()) next.email = "Enter your email address.";
    setErrors(next);
    if (Object.keys(next).length || !mode) return;
    send.mutate(mode);
  }

  function open(how: Mode) {
    setMode(how);
    setRefusal(null);
    setErrors({});
  }

  const idPrefix = `event-${event.id}`;

  return (
    <li className="px-4 py-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-medium text-navy-700">{event.name}</h2>
          <p className="mt-1 text-sm text-slate-600">{event.status_description}</p>
          <p className="mt-2 text-xs text-slate-500">
            {event.preferred_start
              ? new Date(event.preferred_start).toLocaleString("en-SG")
              : "Date to be confirmed"}
            {event.status_changed_at
              ? ` · Status updated ${new Date(event.status_changed_at).toLocaleString("en-SG")}`
              : ""}
          </p>
          {event.venues?.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              {event.venues.map((v) => `${v.name}${v.location ? `, ${v.location}` : ""}`).join("; ")}
            </p>
          )}
          {event.registration_required && event.places_left !== null && (
            <p className="mt-1 text-sm text-slate-700">
              {event.places_left === 0 ? "No places left" : `${event.places_left} places left`}
            </p>
          )}
          {event.registration_required && event.registration_message && (
            <p className="mt-1 text-sm text-amber-800">{event.registration_message}</p>
          )}
          {mine && (
            <p className="mt-1 text-sm font-medium text-navy-700">
              Your status: {mine.status_display}
            </p>
          )}
        </div>
        <StatusBadge
          status={event.status}
          label={event.status_label}
          title={event.status_description}
        />
      </div>

      {done && (
        <p role="status" className="mt-3 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-900">
          {done}
        </p>
      )}
      {refusal && (
        <p role="alert" className="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {refusal}
        </p>
      )}

      {!mode && !done && (canRegister || canJoinWaitlist) && (
        <div className="mt-3 flex gap-3">
          {canRegister && (
            <button
              type="button"
              onClick={() => open("register")}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600"
            >
              Register
            </button>
          )}
          {canJoinWaitlist && (
            <button
              type="button"
              onClick={() => open("waitlist")}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
            >
              Join waiting list
            </button>
          )}
        </div>
      )}

      {mode && (
        <form
          onSubmit={submit}
          noValidate
          aria-label={`${mode === "register" ? "Register for" : "Join the waiting list for"} ${event.name}`}
          className="mt-4 rounded-md border border-slate-200 p-4"
        >
          <Field label="Full name" htmlFor={`${idPrefix}-full_name`} error={errors.full_name}>
            <input
              id={`${idPrefix}-full_name`}
              className={inputClass}
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            />
          </Field>
          <Field label="Email" htmlFor={`${idPrefix}-email`} error={errors.email}>
            <input
              id={`${idPrefix}-email`}
              type="email"
              className={inputClass}
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </Field>
          <Field
            label="Accessibility needs (optional)"
            htmlFor={`${idPrefix}-accessibility_needs`}
            error={errors.accessibility_needs}
          >
            <textarea
              id={`${idPrefix}-accessibility_needs`}
              rows={2}
              className={inputClass}
              value={form.accessibility_needs}
              onChange={(e) => setForm({ ...form, accessibility_needs: e.target.value })}
            />
          </Field>
          <div className="flex gap-3">
            <button
              type="submit"
              disabled={send.isPending}
              className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600"
            >
              {mode === "register" ? "Confirm registration" : "Join waiting list"}
            </button>
            <button
              type="button"
              onClick={() => setMode(null)}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* The API may report the event is full and offer its waiting list. */}
      {mode === "register" && canJoinWaitlist && refusal && (
        <button
          type="button"
          onClick={() => open("waitlist")}
          className="mt-3 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
        >
          Join waiting list instead
        </button>
      )}
    </li>
  );
}

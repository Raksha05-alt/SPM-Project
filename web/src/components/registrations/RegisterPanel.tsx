import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import {
  getRegistrationSummary,
  joinWaitlist,
  registerForEvent,
} from "../../api/registrations";
import { useAuth } from "../../auth/AuthContext";
import { inputClass } from "../Field";
import { WithdrawControl } from "./WithdrawControl";

const FIELD_LABELS: Record<string, string> = {
  full_name: "Full name",
  email: "Email address",
};

/**
 * SCRUM-21/81 - register for one confirmed event, or see why you cannot.
 * SCRUM-14 - withdraw after a summary. SCRUM-19 - join the waiting list of a full event.
 */
export function RegisterPanel({ eventId }: { eventId: number }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    full_name: user ? `${user.first_name} ${user.last_name}`.trim() : "",
    email: user?.email ?? "",
    accessibility_requirements: "",
  });
  const [notice, setNotice] = useState<string | null>(null);
  const summary = useQuery({
    queryKey: ["registration", eventId],
    queryFn: () => getRegistrationSummary(eventId),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["registration", eventId] });
    void queryClient.invalidateQueries({ queryKey: ["my-registrations"] });
  };
  const submit = useMutation({
    mutationFn: (action: "register" | "waitlist"): Promise<{ detail: string }> =>
      action === "register" ? registerForEvent(eventId, form) : joinWaitlist(eventId, form),
    onSuccess: (result) => {
      setNotice(result.detail);
      setOpen(false);
    },
    onSettled: refresh,
  });

  if (summary.isLoading || !summary.data) return null;
  const data = summary.data;
  const body =
    submit.error instanceof ApiError
      ? ((submit.error.body ?? {}) as { detail?: string; missing?: string[] })
      : null;
  const waiting = data.my_status === "WAITLISTED";

  if (data.my_status === "REGISTERED" && data.my_registration) {
    return (
      <div className="mt-2 text-sm">
        <p role="status" className="text-green-800">
          {notice ?? "You are registered for this event."}
        </p>
        <WithdrawControl registrationId={data.my_registration} onDone={refresh} />
      </div>
    );
  }

  // What the attendee may do now: register while places are free, otherwise
  // join the waiting list when the organiser allows one.
  const action: "register" | "waitlist" | null = data.open
    ? "register"
    : data.waitlist_offered
      ? "waitlist"
      : null;

  return (
    <div className="mt-3 text-sm">
      {waiting && data.my_registration && (
        <div className="mb-2">
          <p role="status" className="text-amber-800">
            {notice ??
              `You are number ${data.waitlist_position} on the waiting list. We will tell you if a place opens.`}
          </p>
          <WithdrawControl
            registrationId={data.my_registration}
            label="Leave the waiting list"
            onDone={refresh}
          />
        </div>
      )}
      {!waiting && notice && <p role="status">{notice}</p>}
      {!action && !waiting && <p className="text-slate-500">{data.reason}</p>}
      {action === "register" && data.remaining !== null && (
        <p className="text-slate-500">{data.remaining} places left</p>
      )}
      {action === "waitlist" && (
        <p className="text-slate-500">
          This event is full. {data.waiting} {data.waiting === 1 ? "person is" : "people are"}{" "}
          waiting.
        </p>
      )}
      {action && !open && (
        <button
          type="button"
          className="mt-2 rounded-md bg-navy-700 px-3 py-1 text-white"
          onClick={() => setOpen(true)}
        >
          {action === "register" ? "Register" : "Join the waiting list"}
        </button>
      )}
      {action && open && (
        <form
          className="mt-2 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            setNotice(null);
            submit.mutate(action);
          }}
        >
          <label className="block">
            Full name
            <input
              className={inputClass}
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            />
          </label>
          <label className="block">
            Email address
            <input
              type="email"
              className={inputClass}
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </label>
          <label className="block">
            Accessibility requirements (optional)
            <textarea
              className={inputClass}
              rows={2}
              value={form.accessibility_requirements}
              onChange={(e) => setForm({ ...form, accessibility_requirements: e.target.value })}
            />
          </label>
          <div className="flex gap-2">
            <button
              type="submit"
              className="rounded-md bg-navy-700 px-3 py-1 text-white disabled:opacity-50"
              disabled={submit.isPending}
            >
              {action === "register" ? "Confirm registration" : "Join waiting list"}
            </button>
            <button type="button" className="underline" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {body && (
        <div role="alert" className="mt-2 text-red-700">
          <p>{body.detail ?? "That did not go through."}</p>
          {body.missing && body.missing.length > 0 && (
            <ul className="list-inside list-disc">
              {body.missing.map((field) => (
                <li key={field}>{FIELD_LABELS[field] ?? field}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

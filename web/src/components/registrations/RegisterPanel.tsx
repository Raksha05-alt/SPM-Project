import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { getRegistrationSummary, registerForEvent } from "../../api/registrations";
import { useAuth } from "../../auth/AuthContext";
import { inputClass } from "../Field";

const FIELD_LABELS: Record<string, string> = {
  full_name: "Full name",
  email: "Email address",
};

/** SCRUM-21/81 - register for one confirmed event, or see why you cannot. */
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
  const register = useMutation({
    mutationFn: () => registerForEvent(eventId, form),
    onSuccess: (result) => {
      setNotice(result.detail);
      setOpen(false);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["registration", eventId] });
      void queryClient.invalidateQueries({ queryKey: ["my-registrations"] });
    },
  });

  if (summary.isLoading || !summary.data) return null;
  const data = summary.data;
  const body =
    register.error instanceof ApiError
      ? ((register.error.body ?? {}) as {
          detail?: string;
          missing?: string[];
          registration?: { registered_at: string };
        })
      : null;

  if (data.my_status === "REGISTERED") {
    return (
      <p role="status" className="mt-2 text-sm text-green-800">
        {notice ?? "You are registered for this event."}
      </p>
    );
  }
  if (!data.open) {
    return <p className="mt-2 text-sm text-slate-500">{data.reason}</p>;
  }

  return (
    <div className="mt-3 text-sm">
      {data.remaining !== null && (
        <p className="text-slate-500">{data.remaining} places left</p>
      )}
      {!open ? (
        <button
          type="button"
          className="mt-2 rounded-md bg-navy-700 px-3 py-1 text-white"
          onClick={() => setOpen(true)}
        >
          Register
        </button>
      ) : (
        <form
          className="mt-2 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            setNotice(null);
            register.mutate();
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
              disabled={register.isPending}
            >
              Confirm registration
            </button>
            <button type="button" className="underline" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {body && (
        <div role="alert" className="mt-2 text-red-700">
          <p>{body.detail ?? "Registration did not go through."}</p>
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

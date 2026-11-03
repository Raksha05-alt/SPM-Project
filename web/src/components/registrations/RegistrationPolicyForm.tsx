import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { getRegistrationPolicy, updateRegistrationPolicy } from "../../api/registrations";
import { inputClass } from "../Field";

/** ISO instant -> value for a datetime-local input, in the browser's time zone. */
function toLocalInput(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function fromLocalInput(value: string) {
  return value ? new Date(value).toISOString() : null;
}

/** SCRUM-81 - the organiser's registration settings: on/off, period, cap, manual close. */
export function RegistrationPolicyForm({ eventId }: { eventId: number }) {
  const queryClient = useQueryClient();
  const policy = useQuery({
    queryKey: ["registration-policy", eventId],
    queryFn: () => getRegistrationPolicy(eventId),
  });
  const [form, setForm] = useState({
    enabled: false,
    opens_at: "",
    closes_at: "",
    capacity: "",
    manually_closed: false,
  });
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (policy.data) {
      setForm({
        enabled: policy.data.enabled,
        opens_at: toLocalInput(policy.data.opens_at),
        closes_at: toLocalInput(policy.data.closes_at),
        capacity: policy.data.capacity?.toString() ?? "",
        manually_closed: policy.data.manually_closed,
      });
    }
  }, [policy.data]);
  const save = useMutation({
    mutationFn: () =>
      updateRegistrationPolicy(eventId, {
        enabled: form.enabled,
        opens_at: fromLocalInput(form.opens_at),
        closes_at: fromLocalInput(form.closes_at),
        capacity: form.capacity ? Number(form.capacity) : null,
        manually_closed: form.manually_closed,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["registration-policy", eventId], data);
      setSaved(true);
    },
  });

  if (policy.isLoading || !policy.data) return null;
  const errors =
    save.error instanceof ApiError ? ((save.error.body ?? {}) as Record<string, string[]>) : {};

  return (
    <section
      aria-label="Registration"
      className="mb-6 rounded-lg border border-slate-200 bg-white p-6 text-sm"
    >
      <h2 className="mb-1 text-lg font-semibold text-navy-700">Registration</h2>
      <p className="mb-3 text-slate-600">
        {policy.data.registered} registered
        {policy.data.capacity !== null && ` of ${policy.data.capacity}`}
        {policy.data.full ? " · Full" : ""} · {policy.data.open ? "Open now" : "Not open now"}
      </p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          setSaved(false);
          save.mutate();
        }}
      >
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
          />
          Allow attendees to register
        </label>
        <label className="block">
          Registration opens
          <input
            type="datetime-local"
            className={inputClass}
            value={form.opens_at}
            onChange={(e) => setForm({ ...form, opens_at: e.target.value })}
          />
        </label>
        <label className="block">
          Registration closes
          <input
            type="datetime-local"
            className={inputClass}
            value={form.closes_at}
            onChange={(e) => setForm({ ...form, closes_at: e.target.value })}
          />
          {errors.closes_at && <span className="text-red-700">{errors.closes_at[0]}</span>}
        </label>
        <label className="block">
          Registration capacity
          <input
            type="number"
            min={1}
            className={inputClass}
            value={form.capacity}
            onChange={(e) => setForm({ ...form, capacity: e.target.value })}
          />
          {errors.capacity && <span className="text-red-700">{errors.capacity[0]}</span>}
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.manually_closed}
            onChange={(e) => setForm({ ...form, manually_closed: e.target.checked })}
          />
          Close registration now
        </label>
        <button
          type="submit"
          className="rounded-md bg-navy-700 px-4 py-2 text-white disabled:opacity-50"
          disabled={save.isPending}
        >
          Save registration settings
        </button>
        {saved && <p role="status">Registration settings saved.</p>}
        {save.error && !errors.capacity && !errors.closes_at && (
          <p role="alert" className="text-red-700">
            {(save.error instanceof ApiError &&
              (save.error.body as { detail?: string } | null)?.detail) ||
              "The settings could not be saved."}
          </p>
        )}
      </form>
    </section>
  );
}

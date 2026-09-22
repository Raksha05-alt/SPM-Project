import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { createDraft, deleteDraft, getEvent, updateDraft } from "../api/events";
import type { EventDraft } from "../api/events";
import { Field, inputClass } from "../components/Field";
import { StatusBadge } from "../components/StatusBadge";

const EMPTY: EventDraft = {
  name: "",
  purpose: "",
  description: "",
  preferred_start: null,
  preferred_end: null,
  expected_attendance: null,
  required_layout: "",
  accessibility_needs: "",
  equipment_notes: "",
  registration_required: false,
};

function localDateTime(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function EventRequestForm() {
  const { id } = useParams();
  const eventId = id ? Number(id) : null;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [form, setForm] = useState<EventDraft>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<string | null>(null);

  const { data: existing, isLoading, isError } = useQuery({
    queryKey: ["events", eventId],
    queryFn: () => getEvent(eventId as number),
    enabled: eventId !== null,
  });

  // US-03.1 AC3 - reopening a draft shows every value unchanged.
  // TanStack Query v5 removed the onSuccess callback from useQuery, so the
  // form is seeded from the query result here instead.
  useEffect(() => {
    if (existing) setForm({ ...EMPTY, ...existing });
    else if (eventId === null) setForm(EMPTY);
  }, [existing, eventId]);

  const readOnly = existing ? !existing.is_editable : false;

  function set<K extends keyof EventDraft>(key: K, value: EventDraft[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleApiError(error: unknown) {
    if (error instanceof ApiError && error.status === 400 && error.body) {
      const body = error.body as Record<string, string[] | string>;
      const next: Record<string, string> = {};
      for (const [key, value] of Object.entries(body)) {
        if (key === "missing_fields" || key === "detail") continue;
        next[key] = Array.isArray(value) ? value[0] : String(value);
      }
      setFieldErrors(next);
      setBanner(error.message);
      return;
    }
    setBanner("We could not save this request. Please try again.");
  }

  const save = useMutation({
    mutationFn: async () => {
      setFieldErrors({});
      return eventId === null ? createDraft(form) : updateDraft(eventId, form);
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ["events"] });
      setBanner("Draft saved.");
      if (eventId === null) navigate(`/organiser/requests/${saved.id}`, { replace: true });
    },
    onError: handleApiError,
  });

  const remove = useMutation({
    mutationFn: () => deleteDraft(eventId as number),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["events"] });
      navigate("/organiser", { replace: true });
    },
    onError: () => setBanner("We could not delete this draft. Please try again."),
  });

  if (eventId !== null && isLoading) return <p>Loading your draft…</p>;
  if (eventId !== null && isError) return <p role="alert">We could not load this draft.</p>;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-navy-700">
          {eventId === null ? "New event request" : existing?.name || "Event request"}
        </h1>
        {existing && (
          <StatusBadge
            status={existing.status}
            label={existing.status_label}
            title={existing.status_description}
          />
        )}
      </div>

      {existing && (
        <p className="mb-4 text-sm text-slate-600">{existing.status_description}</p>
      )}

      {banner && (
        <p role="status" className="mb-4 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-900">
          {banner}
        </p>
      )}

      <fieldset disabled={readOnly} className="rounded-lg border border-slate-200 bg-white p-6">
        <Field label="Event name" htmlFor="name" error={fieldErrors.name}>
          <input
            id="name"
            className={inputClass}
            value={form.name ?? ""}
            onChange={(e) => set("name", e.target.value)}
          />
        </Field>
        <Field label="Purpose" htmlFor="purpose" error={fieldErrors.purpose}>
          <input
            id="purpose"
            className={inputClass}
            value={form.purpose ?? ""}
            onChange={(e) => set("purpose", e.target.value)}
          />
        </Field>
        <Field label="Description" htmlFor="description">
          <textarea
            id="description"
            rows={3}
            className={inputClass}
            value={form.description ?? ""}
            onChange={(e) => set("description", e.target.value)}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Preferred start" htmlFor="preferred_start" error={fieldErrors.preferred_start}>
            <input
              id="preferred_start"
              type="datetime-local"
              className={inputClass}
              value={localDateTime(form.preferred_start)}
              onChange={(e) =>
                set("preferred_start", e.target.value ? new Date(e.target.value).toISOString() : null)
              }
            />
          </Field>
          <Field label="Preferred end" htmlFor="preferred_end" error={fieldErrors.preferred_end}>
            <input
              id="preferred_end"
              type="datetime-local"
              className={inputClass}
              value={localDateTime(form.preferred_end)}
              onChange={(e) =>
                set("preferred_end", e.target.value ? new Date(e.target.value).toISOString() : null)
              }
            />
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Expected attendance"
            htmlFor="expected_attendance"
            error={fieldErrors.expected_attendance}
          >
            <input
              id="expected_attendance"
              type="number"
              min={1}
              className={inputClass}
              value={form.expected_attendance ?? ""}
              onChange={(e) =>
                set("expected_attendance", e.target.value ? Number(e.target.value) : null)
              }
            />
          </Field>
          <Field label="Required room layout" htmlFor="required_layout">
            <select
              id="required_layout"
              className={inputClass}
              value={form.required_layout ?? ""}
              onChange={(e) => set("required_layout", e.target.value)}
            >
              <option value="">No preference</option>
              <option value="CLASSROOM">Classroom</option>
              <option value="THEATRE">Theatre</option>
              <option value="BOARDROOM">Boardroom</option>
              <option value="BANQUET">Banquet</option>
              <option value="EXHIBITION">Exhibition</option>
            </select>
          </Field>
        </div>

        <Field label="Accessibility needs" htmlFor="accessibility_needs">
          <textarea
            id="accessibility_needs"
            rows={2}
            className={inputClass}
            value={form.accessibility_needs ?? ""}
            onChange={(e) => set("accessibility_needs", e.target.value)}
          />
        </Field>
        <Field label="Equipment and technical requirements" htmlFor="equipment_notes">
          <textarea
            id="equipment_notes"
            rows={2}
            className={inputClass}
            value={form.equipment_notes ?? ""}
            onChange={(e) => set("equipment_notes", e.target.value)}
          />
        </Field>

        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={Boolean(form.registration_required)}
            onChange={(e) => set("registration_required", e.target.checked)}
          />
          Attendees will need to register for this event
        </label>
      </fieldset>

      {!readOnly && (
        <div className="mt-6 flex gap-3">
          {/* US-03.1 AC2 - saving works however incomplete the form is. */}
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending || remove.isPending}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50"
          >
            Save draft
          </button>
          {eventId !== null && (
            <button type="button" disabled={remove.isPending || save.isPending}
              onClick={() => { if (window.confirm("Delete this draft?")) remove.mutate(); }}
              className="rounded-md border border-red-300 px-4 py-2 text-sm text-red-700">
              Delete draft
            </button>
          )}
          <button type="button" onClick={() => navigate("/organiser")}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm">
            Back to drafts
          </button>
        </div>
      )}
    </div>
  );
}

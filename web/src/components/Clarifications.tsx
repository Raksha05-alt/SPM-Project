import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { addClarificationNote } from "../api/events";
import type { Clarification } from "../types";
import { inputClass } from "./Field";

/** Fields a coordinator can point the client to. Matches the API's list. */
export const CLARIFIABLE_FIELDS: { value: string; label: string }[] = [
  { value: "name", label: "Event name" },
  { value: "purpose", label: "Purpose" },
  { value: "description", label: "Description" },
  { value: "preferred_start", label: "Preferred start" },
  { value: "preferred_end", label: "Preferred end" },
  { value: "expected_attendance", label: "Expected attendance" },
  { value: "required_layout", label: "Required room layout" },
  { value: "accessibility_needs", label: "Accessibility needs" },
  { value: "equipment_notes", label: "Equipment and technical requirements" },
  { value: "registration_required", label: "Registration required" },
];

const LABELS = Object.fromEntries(CLARIFIABLE_FIELDS.map((f) => [f.value, f.label]));

export function fieldLabel(field: string) {
  return LABELS[field] ?? field;
}

/** The coordinator's current, unanswered question to the client, prominently. */
export function OpenClarification({ clarification }: { clarification: Clarification }) {
  return (
    <div role="alert" className="mb-4 rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p className="font-medium">
        {clarification.requested_by_name ?? "Your coordinator"} needs more information:
      </p>
      <p className="mt-1 whitespace-pre-line">{clarification.message}</p>
      {clarification.fields.length > 0 && (
        <p className="mt-2">Please check: {clarification.fields.map(fieldLabel).join(", ")}</p>
      )}
    </div>
  );
}

/** Every clarification round on the event, newest first, kept after it is answered. */
export function ClarificationHistory({ clarifications }: { clarifications: Clarification[] }) {
  if (clarifications.length === 0) return null;
  return (
    <section aria-label="Clarification history" className="mt-6">
      <h2 className="mb-2 text-sm font-semibold text-navy-700">Clarification history</h2>
      <ol className="space-y-3">
        {clarifications.map((c) => (
          <li key={c.id} className="rounded-md border border-slate-200 bg-white p-3 text-sm">
            <p className="whitespace-pre-line text-slate-800">{c.message}</p>
            {c.fields.length > 0 && (
              <p className="mt-1 text-xs text-slate-600">
                Items: {c.fields.map(fieldLabel).join(", ")}
              </p>
            )}
            <p className="mt-1 text-xs text-slate-500">
              Asked by {c.requested_by_name ?? "a coordinator"} ·{" "}
              {new Date(c.requested_at).toLocaleString("en-SG")} ·{" "}
              {c.resolved_at
                ? `answered ${new Date(c.resolved_at).toLocaleString("en-SG")}`
                : "awaiting answer"}
            </p>
            {(c.comments ?? []).length > 0 && (
              <ul aria-label="Clarification notes" className="mt-2 space-y-1 border-l-2 border-slate-200 pl-3">
                {(c.comments ?? []).map((note) => (
                  <li key={note.id} className="text-xs text-slate-700">
                    <span className="font-medium">
                      {note.author_name ?? "Someone"}
                      {note.author_role ? ` (${note.author_role})` : ""}
                    </span>
                    : {note.message}{" "}
                    <span className="text-slate-500">
                      · {new Date(note.created_at).toLocaleString("en-SG")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * Week 9 clarification - the conversation happens offline (phone, email, meetings),
 * and the system records what was said so that both sides can track it.
 */
export function ClarificationNoteForm({
  eventId,
  clarificationId,
  invalidate,
}: {
  eventId: number;
  clarificationId?: number;
  invalidate: unknown[];
}) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => addClarificationNote(eventId, message.trim(), clarificationId),
    onSuccess: () => {
      setMessage("");
      void queryClient.invalidateQueries({ queryKey: invalidate });
    },
    onError: (err) => setError(err instanceof Error ? err.message : "We could not save the note."),
  });

  function submit() {
    if (!message.trim()) {
      setError("Write the note before saving it.");
      return;
    }
    setError(null);
    save.mutate();
  }

  return (
    <div className="mt-3">
      <label htmlFor="clarification-note" className="mb-1 block text-sm font-medium">
        Record what was agreed (offline answers, calls, emails)
      </label>
      <textarea
        id="clarification-note"
        rows={2}
        className={inputClass}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
      />
      {error && (
        <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
          {error}
        </p>
      )}
      <div className="mt-2 flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={save.isPending}
          className="rounded-md border border-slate-300 bg-white px-3 py-1 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
        >
          Save note
        </button>
      </div>
    </div>
  );
}

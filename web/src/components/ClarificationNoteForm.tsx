import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { addClarificationNote } from "../api/events";
import type { EventRequest } from "../types";
import { inputClass } from "./Field";

/** SCRUM-92 AC1 - the client or the assigned coordinator records an offline conversation. */
export function ClarificationNoteForm({
  eventId,
  onSaved,
}: {
  eventId: number;
  onSaved: (updated: EventRequest) => void;
}) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => addClarificationNote(eventId, body.trim()),
    onSuccess: (updated) => {
      setBody("");
      onSaved(updated);
    },
  });

  function submit() {
    // AC2 - the API also refuses an empty note.
    if (!body.trim()) {
      setError("Write the note before saving it.");
      return;
    }
    setError(null);
    save.mutate();
  }

  return (
    <section aria-label="Add a clarification note" className="mt-4">
      <label htmlFor="clarification-note" className="mb-1 block text-sm font-medium">
        Add a note from your conversation
      </label>
      <textarea
        id="clarification-note"
        rows={3}
        className={inputClass}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      {(error ?? save.error) && (
        <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
          {error ?? save.error?.message}
        </p>
      )}
      <div className="mt-2 flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={save.isPending}
          className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
        >
          Save note
        </button>
      </div>
    </section>
  );
}

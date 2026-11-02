import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  createLayout,
  deleteLayout,
  reinstateLayout,
  retireLayout,
  updateLayout,
} from "../api/layouts";
import { Field, inputClass } from "../components/Field";
import { useLayouts } from "../components/layouts/useLayouts";
import { fieldErrors } from "../components/venues/VenueForm";
import type { LayoutType } from "../types";

type Usage = { venues: number; event_requests: number; venue_bookings: number };

const EMPTY = { code: "", name: "", description: "" };

function describeUsage(usage: Usage) {
  return [
    [usage.venues, "venue"],
    [usage.event_requests, "event request"],
    [usage.venue_bookings, "venue booking"],
  ]
    .filter(([count]) => Number(count) > 0)
    .map(([count, noun]) => `${count} ${noun}${count === 1 ? "" : "s"}`)
    .join(", ");
}

/** SCRUM-91 - Venue Staff maintain the room layout catalogue. */
export function RoomLayouts() {
  const queryClient = useQueryClient();
  const { layouts, isLoading, isError } = useLayouts();
  const [draft, setDraft] = useState(EMPTY);
  const [editing, setEditing] = useState<{ code: string; name: string; description: string }>();
  const [confirmDelete, setConfirmDelete] = useState<string>();
  const [inUse, setInUse] = useState<{ layout: LayoutType; message: string; usage: Usage }>();
  const [notice, setNotice] = useState<string>();

  function refresh(message: string) {
    setNotice(message);
    // Names appear on venues and events too (AC2), so refresh those as well.
    void queryClient.invalidateQueries({ queryKey: ["layouts"] });
    void queryClient.invalidateQueries({ queryKey: ["venues"] });
    void queryClient.invalidateQueries({ queryKey: ["venue"] });
  }

  const create = useMutation({
    mutationFn: () => createLayout(draft),
    onSuccess: (layout) => {
      setDraft(EMPTY);
      refresh(`Added ${layout.name}.`);
    },
  });
  const save = useMutation({
    mutationFn: (edit: { code: string; name: string; description: string }) =>
      updateLayout(edit.code, { name: edit.name, description: edit.description }),
    onSuccess: (layout) => {
      setEditing(undefined);
      refresh(`Saved ${layout.name}.`);
    },
  });
  const setActive = useMutation({
    mutationFn: ({ code, active }: { code: string; active: boolean }) =>
      active ? reinstateLayout(code) : retireLayout(code),
    onSuccess: (layout) => {
      setInUse(undefined);
      refresh(
        layout.is_active
          ? `${layout.name} can be chosen again.`
          : `Retired ${layout.name}. It stays on existing records but can no longer be chosen.`,
      );
    },
  });
  const remove = useMutation({
    mutationFn: (layout: LayoutType) => deleteLayout(layout.code),
    onSuccess: (_, layout) => {
      setConfirmDelete(undefined);
      refresh(`Deleted ${layout.name}.`);
    },
    onError: (error, layout) => {
      setConfirmDelete(undefined);
      // AC3 - a layout in use is refused; offer to retire it instead.
      if (error instanceof ApiError && error.status === 409) {
        const body = error.body as { usage: Usage };
        setInUse({ layout, message: error.message, usage: body.usage });
      }
    },
  });

  if (isLoading) return <p className="text-slate-500">Loading room layouts…</p>;
  if (isError) return <p role="alert">We could not load the room layouts.</p>;

  const createErrors = fieldErrors(create.error);
  const saveErrors = fieldErrors(save.error);

  return (
    <div>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-navy-700">Room layouts</h1>
        <Link to="/venues" className="text-sm text-navy-700 underline">
          Back to venues
        </Link>
      </div>

      {notice && (
        <p role="status" className="mb-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
          {notice}
        </p>
      )}
      {inUse && (
        <div role="alert" className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
          <p>{inUse.message}</p>
          <p className="mt-1">Used by {describeUsage(inUse.usage)}.</p>
          {inUse.layout.is_active && (
            <button
              type="button"
              onClick={() => setActive.mutate({ code: inUse.layout.code, active: false })}
              className="mt-2 rounded-md border border-amber-400 bg-white px-3 py-1 text-sm font-medium"
            >
              Retire {inUse.layout.name} instead
            </button>
          )}
        </div>
      )}
      {(setActive.error || remove.error) && !inUse && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {(setActive.error ?? remove.error)?.message}
        </p>
      )}

      <div className="mb-8 overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Code</th>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Description</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {layouts.map((layout) =>
              editing?.code === layout.code ? (
                <tr key={layout.code}>
                  <td className="px-4 py-3 font-mono">{layout.code}</td>
                  <td className="px-4 py-3">
                    <input
                      aria-label={`Name for ${layout.code}`}
                      className={inputClass}
                      value={editing.name}
                      onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                    />
                    {saveErrors.name && (
                      <p role="alert" className="mt-1 text-xs text-rose-700">
                        {saveErrors.name}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <input
                      aria-label={`Description for ${layout.code}`}
                      className={inputClass}
                      value={editing.description}
                      onChange={(e) => setEditing({ ...editing, description: e.target.value })}
                    />
                  </td>
                  <td className="px-4 py-3" />
                  <td className="space-x-2 whitespace-nowrap px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => save.mutate(editing)}
                      disabled={save.isPending}
                      className="rounded-md bg-navy-700 px-3 py-1 font-medium text-white disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(undefined)}
                      className="rounded-md border border-slate-300 px-3 py-1"
                    >
                      Cancel
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={layout.code}>
                  <td className="px-4 py-3 font-mono">{layout.code}</td>
                  <td className="px-4 py-3 font-medium text-navy-700">{layout.name}</td>
                  <td className="px-4 py-3 text-slate-600">{layout.description || "—"}</td>
                  <td className="px-4 py-3">{layout.is_active ? "Active" : "Retired"}</td>
                  <td className="space-x-2 whitespace-nowrap px-4 py-3 text-right">
                    {confirmDelete === layout.code ? (
                      <>
                        <span>Delete {layout.name}?</span>
                        <button
                          type="button"
                          onClick={() => remove.mutate(layout)}
                          disabled={remove.isPending}
                          className="rounded-md bg-rose-700 px-3 py-1 font-medium text-white"
                        >
                          Confirm delete
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(undefined)}
                          className="rounded-md border border-slate-300 px-3 py-1"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          aria-label={`Edit ${layout.name}`}
                          onClick={() => {
                            save.reset();
                            setEditing({
                              code: layout.code,
                              name: layout.name,
                              description: layout.description,
                            });
                          }}
                          className="rounded-md border border-slate-300 px-3 py-1"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          aria-label={`${layout.is_active ? "Retire" : "Reinstate"} ${layout.name}`}
                          onClick={() =>
                            setActive.mutate({ code: layout.code, active: !layout.is_active })
                          }
                          className="rounded-md border border-slate-300 px-3 py-1"
                        >
                          {layout.is_active ? "Retire" : "Reinstate"}
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete ${layout.name}`}
                          onClick={() => {
                            setInUse(undefined);
                            setConfirmDelete(layout.code);
                          }}
                          className="rounded-md border border-rose-300 px-3 py-1 text-rose-800"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>

      <form
        aria-label="Add a layout"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
        className="rounded-lg border border-slate-200 bg-white p-6"
      >
        <h2 className="mb-4 text-lg font-semibold text-navy-700">Add a layout</h2>
        <div className="grid gap-x-6 sm:grid-cols-2">
          <Field
            label="Code"
            htmlFor="layout-code"
            hint="Capital letters, digits or underscores. It cannot be changed later."
            error={createErrors.code}
          >
            <input
              id="layout-code"
              className={inputClass}
              value={draft.code}
              onChange={(e) => setDraft({ ...draft, code: e.target.value })}
            />
          </Field>
          <Field label="Name" htmlFor="layout-name" error={createErrors.name}>
            <input
              id="layout-name"
              className={inputClass}
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </Field>
        </div>
        <Field label="Description" htmlFor="layout-description">
          <textarea
            id="layout-description"
            className={inputClass}
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          />
        </Field>
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          Add layout
        </button>
      </form>
    </div>
  );
}

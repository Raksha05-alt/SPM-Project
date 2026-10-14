import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createLayout,
  deleteLayout,
  listLayouts,
  updateLayout,
  type LayoutType,
} from "../../api/layouts";
import { fieldErrorsOf } from "../../api/planning";
import { ApiError } from "../../api/client";
import { Field, inputClass } from "../../components/Field";
import { VenueNav } from "./VenueCatalogue";

const secondary =
  "rounded-md border border-slate-300 bg-white px-3 py-1 text-sm font-medium hover:bg-slate-50 disabled:opacity-50";

function LayoutRow({ layout, onChange }: { layout: LayoutType; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(layout.name);
  const [description, setDescription] = useState(layout.description);

  const save = useMutation({
    mutationFn: () => updateLayout(layout.id, { name: name.trim(), description }),
    onSuccess: () => {
      setEditing(false);
      onChange();
    },
  });
  const toggle = useMutation({
    mutationFn: () => updateLayout(layout.id, { is_active: !layout.is_active }),
    onSuccess: onChange,
  });
  const remove = useMutation({ mutationFn: () => deleteLayout(layout.id), onSuccess: onChange });
  const error = save.error ?? toggle.error ?? remove.error;

  return (
    <li className="py-3 text-sm">
      {editing ? (
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Name" htmlFor={`layout-name-${layout.id}`}>
            <input
              id={`layout-name-${layout.id}`}
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Description" htmlFor={`layout-description-${layout.id}`}>
            <input
              id={`layout-description-${layout.id}`}
              className={inputClass}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <div className="flex gap-2 sm:col-span-2">
            <button type="button" className={secondary} onClick={() => setEditing(false)}>
              Discard
            </button>
            <button
              type="button"
              className={secondary}
              disabled={save.isPending || !name.trim()}
              onClick={() => save.mutate()}
            >
              Save layout
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="font-medium">
              {layout.name}{" "}
              <span className="font-mono text-xs font-normal text-slate-500">{layout.code}</span>
              {!layout.is_active && (
                <span className="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-xs text-slate-700">
                  Retired
                </span>
              )}
            </p>
            {layout.description && <p className="text-xs text-slate-600">{layout.description}</p>}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className={secondary}
              onClick={() => setEditing(true)}
              aria-label={`Edit ${layout.name}`}
            >
              Edit
            </button>
            <button
              type="button"
              className={secondary}
              disabled={toggle.isPending}
              onClick={() => toggle.mutate()}
            >
              {layout.is_active ? "Retire" : "Reinstate"}
            </button>
            <button
              type="button"
              className="rounded-md border border-rose-300 bg-white px-3 py-1 text-sm font-medium text-rose-800 hover:bg-rose-50 disabled:opacity-50"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
              aria-label={`Delete ${layout.name}`}
            >
              Delete
            </button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 rounded-md bg-rose-50 p-2 text-sm text-rose-800">
          {error.message}
        </p>
      )}
    </li>
  );
}

/**
 * Week 7 clarification - "the Venue Catalogue maintains information about supported
 * room layouts ... it should have the capability to add, edit, delete".
 */
export function LayoutCatalogue() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({ queryKey: ["layouts"], queryFn: listLayouts });
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["layouts"] });
  }

  const add = useMutation({
    mutationFn: () => createLayout({ code: code.trim(), name: name.trim(), description }),
    onSuccess: () => {
      setCode("");
      setName("");
      setDescription("");
      setErrors({});
      refresh();
    },
    onError: (error) => {
      if (error instanceof ApiError) setErrors(fieldErrorsOf(error.body));
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!code.trim()) found.code = "Enter a short code, for example U_SHAPE.";
    if (!name.trim()) found.name = "Enter the layout name.";
    setErrors(found);
    if (Object.keys(found).length === 0) add.mutate();
  }

  return (
    <div>
      <VenueNav />
      <h1 className="mb-2 text-2xl font-semibold text-navy-700">Room layouts</h1>
      <p className="mb-6 text-sm text-slate-500">
        Layouts offered to venues, event requests and bookings. A layout in use cannot be deleted;
        retire it to stop it being chosen for anything new.
      </p>

      <section className="rounded-lg border border-slate-200 bg-white p-6">
        {isLoading && <p className="text-sm text-slate-500">Loading layouts…</p>}
        {isError && <p role="alert">We could not load the layouts.</p>}
        <ul aria-label="Layouts" className="divide-y divide-slate-200">
          {data?.map((layout) => <LayoutRow key={layout.id} layout={layout} onChange={refresh} />)}
        </ul>
      </section>

      <form
        onSubmit={submit}
        noValidate
        className="mt-6 rounded-lg border border-slate-200 bg-white p-6"
      >
        <h2 className="mb-3 text-sm font-semibold text-navy-700">Add a layout</h2>
        <div className="grid gap-x-4 sm:grid-cols-3">
          <Field label="Code" htmlFor="new-layout-code" error={errors.code}>
            <input
              id="new-layout-code"
              className={inputClass}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </Field>
          <Field label="Name" htmlFor="new-layout-name" error={errors.name}>
            <input
              id="new-layout-name"
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Description" htmlFor="new-layout-description">
            <input
              id="new-layout-description"
              className={inputClass}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </div>
        {add.error && Object.keys(errors).length === 0 && (
          <p role="alert" className="mb-3 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
            {add.error.message}
          </p>
        )}
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={add.isPending}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
          >
            Add layout
          </button>
        </div>
      </form>
    </div>
  );
}

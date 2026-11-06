import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { updateMe, type AccountChanges } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Field, inputClass } from "../components/Field";

type Draft = Required<AccountChanges>;

function errorsOf(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const body = (error.body ?? {}) as Record<string, unknown>;
  const errors: Record<string, string> = {};
  for (const field of ["first_name", "last_name", "email", "non_field_errors"]) {
    const value = body[field];
    if (Array.isArray(value) && typeof value[0] === "string") errors[field] = value[0];
  }
  return errors;
}

/**
 * SCRUM-2 - the signed-in user sees their account (AC1) and maintains their
 * own name and email address (AC2/AC4). Role and organisation are shown but
 * cannot be changed here; the API refuses any attempt (AC3).
 */
export function AccountPage() {
  const { user, updateUser } = useAuth();
  const [draft, setDraft] = useState<Draft>({
    first_name: user?.first_name ?? "",
    last_name: user?.last_name ?? "",
    email: user?.email ?? "",
  });
  const [saved, setSaved] = useState("");
  const save = useMutation({
    mutationFn: () => {
      const changes: AccountChanges = {};
      (Object.keys(draft) as (keyof Draft)[]).forEach((key) => {
        if (user && draft[key] !== user[key]) changes[key] = draft[key];
      });
      return updateMe(changes);
    },
    onSuccess: (updated) => {
      const { changed_fields, ...account } = updated;
      const emailChanged = changed_fields.includes("email");
      updateUser(account);
      setDraft({
        first_name: account.first_name,
        last_name: account.last_name,
        email: account.email,
      });
      setSaved(
        changed_fields.length === 0
          ? "Nothing to save: your details are unchanged."
          : emailChanged
            ? "Your details were saved. Sign in with your new email address next time."
            : "Your details were saved.",
      );
    },
  });

  if (!user) return null;
  const errors = errorsOf(save.error);
  const set = (key: keyof Draft, value: string) => {
    setSaved("");
    setDraft((current) => ({ ...current, [key]: value }));
  };

  return (
    <div className="max-w-xl">
      <h1 className="mb-6 text-2xl font-semibold text-navy-700">Your account</h1>

      <section aria-label="Account" className="mb-6 rounded-lg border border-slate-200 bg-white p-5">
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-slate-500">Name</dt>
          <dd>
            {user.first_name} {user.last_name}
          </dd>
          <dt className="text-slate-500">Role</dt>
          <dd>{user.role_label}</dd>
          <dt className="text-slate-500">Organisation</dt>
          <dd>{user.organisation_name ?? "ConnectSphere"}</dd>
          <dt className="text-slate-500">Email address</dt>
          <dd>{user.email}</dd>
        </dl>
        <p className="mt-3 text-xs text-slate-500">
          Your role and organisation are set by ConnectSphere and cannot be changed here.
        </p>
      </section>

      <form
        aria-label="Contact details"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          setSaved("");
          save.mutate();
        }}
        className="space-y-4 rounded-lg border border-slate-200 bg-white p-5"
      >
        <h2 className="text-sm font-semibold text-navy-700">Contact details</h2>
        <Field label="First name" htmlFor="account-first-name" error={errors.first_name}>
          <input
            id="account-first-name"
            className={inputClass}
            value={draft.first_name}
            onChange={(e) => set("first_name", e.target.value)}
            required
          />
        </Field>
        <Field label="Last name (optional)" htmlFor="account-last-name" error={errors.last_name}>
          <input
            id="account-last-name"
            className={inputClass}
            value={draft.last_name}
            onChange={(e) => set("last_name", e.target.value)}
          />
        </Field>
        <Field
          label="Email address"
          htmlFor="account-email"
          hint="You sign in with this address, and others see it as your contact."
          error={errors.email}
        >
          <input
            id="account-email"
            type="email"
            className={inputClass}
            value={draft.email}
            onChange={(e) => set("email", e.target.value)}
            required
          />
        </Field>
        {save.isError && (
          <p role="alert" className="rounded-md bg-rose-50 p-3 text-sm text-rose-800">
            {errors.non_field_errors ??
              (save.error instanceof ApiError
                ? save.error.message
                : "We could not save your details. Try again.")}
          </p>
        )}
        {saved && (
          <p role="status" className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">
            {saved}
          </p>
        )}
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={save.isPending}
            className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
          >
            Save details
          </button>
        </div>
      </form>
    </div>
  );
}

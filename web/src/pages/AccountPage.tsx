import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAccount, updateAccount, type AccountUpdate } from "../api/account";
import { ApiError } from "../api/client";
import { Field, inputClass } from "../components/Field";

const EMPTY: AccountUpdate = { first_name: "", last_name: "", email: "", phone: "" };

/** SCRUM-2 - a user maintains their own contact details; role and organisation are fixed. */
export function AccountPage() {
  const queryClient = useQueryClient();
  const { data: account, isLoading, isError } = useQuery({
    queryKey: ["account"],
    queryFn: getAccount,
  });

  const [form, setForm] = useState<AccountUpdate>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [banner, setBanner] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (account) {
      setForm({
        first_name: account.first_name,
        last_name: account.last_name,
        email: account.email,
        phone: account.phone ?? "",
      });
    }
  }, [account]);

  const save = useMutation({
    mutationFn: () => updateAccount(form),
    onSuccess: (updated) => {
      queryClient.setQueryData(["account"], updated);
      setBanner("Your details have been saved.");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 400 && error.body) {
        const next: Record<string, string> = {};
        for (const [key, value] of Object.entries(error.body as Record<string, unknown>)) {
          if (key === "detail") continue;
          next[key] = Array.isArray(value) ? String(value[0]) : String(value);
        }
        setErrors(next);
        return;
      }
      setFailure(error instanceof Error ? error.message : "We could not save your details.");
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setBanner(null);
    setFailure(null);
    setErrors({});
    save.mutate();
  }

  function set(key: keyof AccountUpdate, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  if (isLoading) return <p className="text-slate-500">Loading your account…</p>;
  if (isError || !account) return <p role="alert">We could not load your account.</p>;

  return (
    <div className="max-w-xl">
      <h1 className="mb-6 text-2xl font-semibold text-navy-700">My account</h1>

      {banner && (
        <p role="status" className="mb-4 rounded-md bg-blue-50 px-3 py-2 text-sm text-blue-900">
          {banner}
        </p>
      )}
      {failure && (
        <p role="alert" className="mb-4 rounded-md bg-rose-50 p-3 text-sm text-rose-800">
          {failure}
        </p>
      )}

      <dl className="mb-6 grid gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Role</dt>
          <dd className="mt-1 text-sm text-slate-800">{account.role_label}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Organisation</dt>
          <dd className="mt-1 text-sm text-slate-800">{account.organisation_name ?? "—"}</dd>
        </div>
      </dl>

      <form
        onSubmit={submit}
        noValidate
        className="rounded-lg border border-slate-200 bg-white p-6"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First name" htmlFor="first_name" error={errors.first_name}>
            <input
              id="first_name"
              className={inputClass}
              value={form.first_name}
              onChange={(e) => set("first_name", e.target.value)}
            />
          </Field>
          <Field label="Last name" htmlFor="last_name" error={errors.last_name}>
            <input
              id="last_name"
              className={inputClass}
              value={form.last_name}
              onChange={(e) => set("last_name", e.target.value)}
            />
          </Field>
        </div>
        <Field label="Email" htmlFor="email" error={errors.email}>
          <input
            id="email"
            type="email"
            className={inputClass}
            value={form.email}
            onChange={(e) => set("email", e.target.value)}
          />
        </Field>
        <Field label="Phone" htmlFor="phone" error={errors.phone}>
          <input
            id="phone"
            type="tel"
            className={inputClass}
            value={form.phone}
            onChange={(e) => set("phone", e.target.value)}
          />
        </Field>
        <button
          type="submit"
          disabled={save.isPending}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600"
        >
          Save changes
        </button>
      </form>
    </div>
  );
}

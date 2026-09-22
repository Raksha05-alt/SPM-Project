import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Field, inputClass } from "../components/Field";

export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await signIn(email, password);
      // US-01.1 AC1 - the API decides the landing path, not the client.
      navigate(user.landing_path, { replace: true });
    } catch {
      // US-01.1 AC3 - one message, never naming which field was wrong.
      setError("Those sign-in details were not recognised.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-24 max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
      <h1 className="mb-1 text-xl font-semibold text-navy-700">Sign in to ConnectSphere</h1>
      <p className="mb-6 text-sm text-slate-500">Event planning and venue booking</p>

      <form onSubmit={handleSubmit} noValidate>
        <Field label="Email" htmlFor="email">
          <input
            id="email"
            type="email"
            autoComplete="username"
            className={inputClass}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </Field>
        <Field label="Password" htmlFor="password">
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            className={inputClass}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>

        {error && (
          <p role="alert" className="mb-4 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-800">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-60"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

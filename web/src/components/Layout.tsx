import { useAuth } from "../auth/AuthContext";

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth();

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <span className="text-lg font-semibold text-navy-700">ConnectSphere</span>
          {user && (
            <div className="flex items-center gap-4 text-sm">
              <span className="text-slate-600">
                {user.first_name} {user.last_name} · {user.role_label}
                {user.organisation_name ? ` · ${user.organisation_name}` : ""}
              </span>
              <button
                type="button"
                onClick={() => void signOut()}
                className="rounded-md border border-slate-300 px-3 py-1 hover:bg-slate-50"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </div>
  );
}

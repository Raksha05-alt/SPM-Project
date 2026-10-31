import { useAuth } from "../auth/AuthContext";
import { Notifications } from "./Notifications";
import { Link } from "react-router-dom";

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth();

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <span className="text-lg font-semibold text-navy-700">ConnectSphere</span>
          {user && (
            <div className="flex items-center gap-4 text-sm">
              {user.role === "COORDINATOR_LEAD" && <Link to="/lead" className="text-navy-700 underline">Coordinator assignments</Link>}
              {["COORDINATOR", "VENUE_STAFF"].includes(user.role) && <Link to="/venues/availability" className="text-navy-700 underline">Venue availability</Link>}
              {user.role === "COORDINATOR" && (
                <Link to="/coordinator/venues" className="text-navy-700 underline">
                  Venue search
                </Link>
              )}
              <Notifications key={user.id} userId={user.id} />
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

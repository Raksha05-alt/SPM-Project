import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthContext, type AuthState } from "./AuthContext";
import { RequireRole } from "./RequireRole";
import type { Role, User } from "../types";

const SECRET = "Coordinator planning notes";

function makeUser(role: Role): User {
  return {
    id: 1,
    email: "someone@example.com",
    first_name: "Some",
    last_name: "One",
    role,
    role_label: role,
    organisation: null,
    organisation_name: null,
    landing_path: role === "ATTENDEE" ? "/events" : "/coordinator",
  };
}

function renderGuarded(state: Partial<AuthState>, roles?: Role[]) {
  const value: AuthState = {
    user: null,
    loading: false,
    signIn: vi.fn(),
    signOut: vi.fn(),
    ...state,
  };

  return render(
    <AuthContext.Provider value={value}>
      <MemoryRouter initialEntries={["/coordinator"]}>
        <Routes>
          <Route
            path="/coordinator"
            element={
              <RequireRole roles={roles}>
                <p>{SECRET}</p>
              </RequireRole>
            }
          />
          <Route path="/login" element={<p>Sign in to ConnectSphere</p>} />
          <Route path="/events" element={<p>Events open for registration</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("RequireRole (US-01.2 / SCRUM-1)", () => {
  it("AC3: a role outside the permitted set never sees the protected content", () => {
    renderGuarded({ user: makeUser("ATTENDEE") }, ["COORDINATOR"]);

    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it("AC3: the refused role is sent to its own landing page, not left on a blank screen", () => {
    renderGuarded({ user: makeUser("ATTENDEE") }, ["COORDINATOR"]);

    expect(screen.getByText("Events open for registration")).toBeInTheDocument();
  });

  it("AC3: entering the address while signed out shows the sign-in page, not the content", () => {
    renderGuarded({ user: null }, ["COORDINATOR"]);

    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
    expect(screen.getByText("Sign in to ConnectSphere")).toBeInTheDocument();
  });

  it("AC3: nothing protected is rendered while the session is still being checked", () => {
    // The gap this closes: rendering children during loading would flash the
    // protected content for one frame before the redirect lands.
    renderGuarded({ user: null, loading: true }, ["COORDINATOR"]);

    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
    expect(screen.queryByText("Sign in to ConnectSphere")).not.toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("a permitted role sees the content", () => {
    renderGuarded({ user: makeUser("COORDINATOR") }, ["COORDINATOR"]);

    expect(screen.getByText(SECRET)).toBeInTheDocument();
  });

  it("a route with no role list only requires a signed-in user", () => {
    renderGuarded({ user: makeUser("ATTENDEE") }, undefined);

    expect(screen.getByText(SECRET)).toBeInTheDocument();
  });

  it("guards every listed role, not just the first", () => {
    renderGuarded({ user: makeUser("VENUE_STAFF") }, ["COORDINATOR", "VENUE_STAFF"]);

    expect(screen.getByText(SECRET)).toBeInTheDocument();
  });
});

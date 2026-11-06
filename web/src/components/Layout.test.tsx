import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { AuthContext } from "../auth/AuthContext";
import type { User } from "../types";
import { Layout } from "./Layout";

vi.mock("../api/notifications", () => ({
  listNotifications: vi.fn(async () => []),
  getUnreadCount: vi.fn(async () => ({ unread: 0 })),
  markNotificationRead: vi.fn(),
}));

const CORA: User = {
  id: 2,
  email: "coordinator@connectsphere.example",
  first_name: "Cora",
  last_name: "Coordinator",
  role: "COORDINATOR",
  role_label: "Event Coordinator",
  organisation: null,
  organisation_name: null,
  landing_path: "/coordinator",
};

function renderLayout(user: User | null, signOut = vi.fn(async () => undefined)) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthContext.Provider value={{ user, loading: false, signIn: vi.fn(), signOut, updateUser: vi.fn() }}>
        <MemoryRouter>
          <Layout>
            <p>Page body</p>
          </Layout>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return signOut;
}

it("SCRUM-2: the signed-in user's name links to their account page", () => {
  renderLayout(CORA);

  const link = screen.getByRole("link", { name: /Cora Coordinator · Event Coordinator/ });
  expect(link).toHaveAttribute("href", "/account");
  expect(screen.getByText("Page body")).toBeInTheDocument();
});

it("shows the organisation and signs out", async () => {
  const signOut = renderLayout({ ...CORA, role: "ORGANISER", role_label: "Event Organiser", organisation_name: "Acme Pte Ltd" });

  expect(screen.getByRole("link", { name: /Event Organiser · Acme Pte Ltd/ })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(signOut).toHaveBeenCalled();
});

it("shows only the page when signed out", () => {
  renderLayout(null);

  expect(screen.queryByRole("link", { name: /account/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
});

it("offers role shortcuts to Leads", () => {
  renderLayout({ ...CORA, role: "COORDINATOR_LEAD", role_label: "Event Coordinator Lead" });

  expect(screen.getByRole("link", { name: "Coordinator assignments" })).toHaveAttribute("href", "/lead");
});

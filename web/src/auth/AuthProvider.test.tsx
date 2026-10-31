import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import * as authApi from "../api/auth";
import { primeCsrf } from "../api/client";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./AuthContext";
import type { User } from "../types";
vi.mock("../api/auth");
vi.mock("../api/client", () => ({ primeCsrf: vi.fn().mockResolvedValue({}) }));
const lead = { id: 1, email: "lead@example.com", role: "COORDINATOR_LEAD" } as User;
const coordinator = { id: 2, email: "coordinator@example.com", role: "COORDINATOR" } as User;
function Controls() {
  const { user, loading, signOut, signIn } = useAuth();
  if (loading) return <p>Checking session</p>;
  return <><p>{user?.email ?? "Signed out"}</p><button onClick={() => void signOut()}>Logout</button>
    <button onClick={() => void signIn("coordinator@example.com", "secret")}>Login</button></>;
}
beforeEach(() => { vi.resetAllMocks(); vi.mocked(primeCsrf).mockResolvedValue({}); });
it("starts signed out when the session has expired", async () => {
  vi.mocked(authApi.fetchMe).mockRejectedValue(new Error("expired"));
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><AuthProvider><Controls /></AuthProvider></QueryClientProvider>);
  expect(await screen.findByText("Signed out")).toBeInTheDocument();
});
it("clears protected event caches when switching users", async () => {
  vi.mocked(authApi.fetchMe).mockResolvedValue(lead);
  vi.mocked(authApi.login).mockResolvedValue(coordinator);
  vi.mocked(authApi.logout).mockResolvedValue(undefined);
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><AuthProvider><Controls /></AuthProvider></QueryClientProvider>);
  await screen.findByText("lead@example.com");
  client.setQueryData(["lead-event", 1, 9], { confidential: "assignment history" });
  client.setQueryData(["event", 9], { confidential: "event" });
  await userEvent.click(screen.getByRole("button", { name: "Logout" }));
  await screen.findByText("Signed out");
  expect(client.getQueryData(["lead-event", 1, 9])).toBeUndefined();
  expect(client.getQueryData(["event", 9])).toBeUndefined();
  client.setQueryData(["event", 9], { confidential: "previous session" });
  await userEvent.click(screen.getByRole("button", { name: "Login" }));
  await waitFor(() => expect(screen.getByText("coordinator@example.com")).toBeInTheDocument());
  expect(client.getQueryData(["event", 9])).toBeUndefined();
});

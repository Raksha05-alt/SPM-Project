import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listNotifications } from "../api/notifications";
import { Notifications } from "./Notifications";

vi.mock("../api/notifications", () => ({ listNotifications: vi.fn() }));

function renderNotifications(userId = 1, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return { client, ...render(<QueryClientProvider client={client}><Notifications key={userId} userId={userId} /></QueryClientProvider>) };
}

describe("SCRUM-51 assignment notifications", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC3: displays persisted messages and their time", async () => {
    vi.mocked(listNotifications).mockResolvedValue([{ id: 1, event: 7, message: "Cora is your coordinator.", created_at: "2026-09-28T01:00:00Z" }]);
    renderNotifications();
    await userEvent.click(screen.getByText("Notifications (0)"));
    expect(await screen.findByText("Cora is your coordinator.")).toBeInTheDocument();
    expect(screen.getByText("Notifications (1)")).toBeInTheDocument();
    expect(document.querySelector("time")).toHaveAttribute("datetime", "2026-09-28T01:00:00Z");
  });

  it("shows an empty state", async () => {
    vi.mocked(listNotifications).mockResolvedValue([]);
    renderNotifications();
    await userEvent.click(screen.getByText("Notifications (0)"));
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
  });

  it("allows retrying a failed load", async () => {
    vi.mocked(listNotifications).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([]);
    renderNotifications();
    await userEvent.click(screen.getByText("Notifications (0)"));
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load notifications.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
  });

  it("does not reuse another user's cached notifications", async () => {
    vi.mocked(listNotifications).mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["notifications", 1], [{ id: 1, event: 7, message: "Private message", created_at: "2026-09-28T01:00:00Z" }]);
    renderNotifications(2, client);
    await userEvent.click(screen.getByText("Notifications (0)"));
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
    expect(screen.queryByText("Private message")).not.toBeInTheDocument();
  });
});

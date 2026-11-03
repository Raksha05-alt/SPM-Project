import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getUnreadCount, listNotifications, markNotificationRead } from "../api/notifications";
import type { AppNotification } from "../types";
import { Notifications } from "./Notifications";

vi.mock("../api/notifications", () => ({
  listNotifications: vi.fn(),
  getUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(),
}));

function notice(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 1,
    event: 7,
    event_name: "Partner Summit",
    kind: "ASSIGNMENT",
    kind_label: "Coordinator assigned",
    message: "Cora is your coordinator.",
    created_at: "2026-09-28T01:00:00Z",
    read_at: null,
    is_read: false,
    destination: { path: "/organiser/requests/7", label: "Open your request" },
    ...overrides,
  };
}

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderNotifications(
  userId = 1,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Notifications key={userId} userId={userId} />
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openPanel() {
  await userEvent.click(screen.getByText(/^Notifications/));
}

describe("SCRUM-79/82 notification centre", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getUnreadCount).mockResolvedValue({ unread: 0 });
  });

  it("AC1 (82) / AC5 (79): shows what happened, the event and when, newest first as sent", async () => {
    vi.mocked(listNotifications).mockResolvedValue([
      notice({ id: 2, kind_label: "Event confirmed", message: "Partner Summit is confirmed." }),
      notice({ id: 1 }),
    ]);
    renderNotifications();
    await openPanel();

    const items = await screen.findAllByRole("button", { name: /Partner Summit/ });
    expect(items.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Unread: Event confirmed - Partner Summit",
      "Unread: Coordinator assigned - Partner Summit",
    ]);
    expect(document.querySelector("time")).toHaveAttribute("datetime", "2026-09-28T01:00:00Z");
  });

  it("AC2: shows the unread count, and opening the list marks nothing read", async () => {
    vi.mocked(listNotifications).mockResolvedValue([notice()]);
    vi.mocked(getUnreadCount).mockResolvedValue({ unread: 3 });
    renderNotifications();

    expect(await screen.findByText("3 unread")).toBeInTheDocument();
    await openPanel();
    await screen.findByText("Cora is your coordinator.");
    expect(markNotificationRead).not.toHaveBeenCalled();
  });

  it("AC2/AC3: selecting a notice marks it read, lowers the count and opens its screen", async () => {
    vi.mocked(listNotifications).mockResolvedValue([notice()]);
    vi.mocked(getUnreadCount).mockResolvedValue({ unread: 1 });
    vi.mocked(markNotificationRead).mockResolvedValue({
      notification: notice({ is_read: true, read_at: "2026-09-28T02:00:00Z" }),
      unread: 0,
    });
    renderNotifications();
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: /Coordinator assigned/ }));

    expect(markNotificationRead).toHaveBeenCalledWith(1);
    expect(await screen.findByTestId("where")).toHaveTextContent("/organiser/requests/7");
    expect(screen.queryByText("1 unread")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Coordinator assigned - Partner Summit" })).toBeInTheDocument();
  });

  it("AC3: a notice I can no longer open stays put and says why", async () => {
    vi.mocked(listNotifications).mockResolvedValue([notice({ destination: null })]);
    vi.mocked(markNotificationRead).mockResolvedValue({
      notification: notice({ destination: null, is_read: true }),
      unread: 0,
    });
    renderNotifications();
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: /Coordinator assigned/ }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "You no longer have access to this event.",
    );
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
  });

  it("says so when marking read fails", async () => {
    vi.mocked(listNotifications).mockResolvedValue([notice()]);
    vi.mocked(markNotificationRead).mockRejectedValue(new Error("offline"));
    renderNotifications();
    await openPanel();

    await userEvent.click(await screen.findByRole("button", { name: /Coordinator assigned/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not open that notification.");
  });

  it("AC4: shows an empty state", async () => {
    vi.mocked(listNotifications).mockResolvedValue([]);
    renderNotifications();
    await openPanel();
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
  });

  it("allows retrying a failed load", async () => {
    vi.mocked(listNotifications).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([]);
    renderNotifications();
    await openPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load notifications.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
  });

  it("does not reuse another user's cached notifications", async () => {
    vi.mocked(listNotifications).mockResolvedValue([]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["notifications", 1], [notice({ message: "Private message" })]);
    renderNotifications(2, client);
    await openPanel();
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
    expect(screen.queryByText("Private message")).not.toBeInTheDocument();
  });

  it("falls back to counting unread notices while the count loads", async () => {
    vi.mocked(listNotifications).mockResolvedValue([notice(), notice({ id: 2, is_read: true })]);
    vi.mocked(getUnreadCount).mockReturnValue(new Promise(() => {}));
    renderNotifications();
    expect(await screen.findByText("1 unread")).toBeInTheDocument();
  });
});

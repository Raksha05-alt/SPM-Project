import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getUnreadCount,
  listNotifications,
  markNotificationRead,
  type AppNotification,
} from "../api/notifications";
import { AuthContext } from "../auth/AuthContext";
import type { Role, User } from "../types";
import { Notifications } from "./Notifications";

vi.mock("../api/notifications", () => ({
  listNotifications: vi.fn(),
  getUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(),
}));

function note(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 1,
    event: 7,
    event_name: "Partner Summit",
    kind_label: "Coordinator assigned",
    message: "Cora is your coordinator.",
    created_at: "2026-09-28T01:00:00Z",
    read_at: null,
    is_read: false,
    ...overrides,
  };
}

function userWith(role: Role, id = 1): User {
  return {
    id,
    email: "u@example.com",
    first_name: "Ada",
    last_name: "User",
    role,
    role_label: role,
    organisation: null,
    organisation_name: null,
    landing_path: "/",
  };
}

function renderNotifications(
  userId = 1,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  role: Role = "ORGANISER",
) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider
          value={{
            user: userWith(role, userId),
            loading: false,
            signIn: vi.fn(),
            signOut: vi.fn(),
          }}
        >
          <MemoryRouter>
            <Routes>
              <Route path="/" element={<Notifications key={userId} userId={userId} />} />
              <Route path="/organiser/requests/:id" element={<p>Organiser event page</p>} />
              <Route path="/events/mine" element={<p>My registrations page</p>} />
            </Routes>
          </MemoryRouter>
        </AuthContext.Provider>
      </QueryClientProvider>,
    ),
  };
}

describe("SCRUM-51 assignment notifications", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getUnreadCount).mockResolvedValue({ unread: 0 });
  });

  it("AC3: displays persisted messages and their time", async () => {
    vi.mocked(listNotifications).mockResolvedValue([note()]);
    vi.mocked(getUnreadCount).mockResolvedValue({ unread: 1 });
    renderNotifications();
    expect(await screen.findByText("Notifications (1)")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Notifications (1)"));
    expect(await screen.findByText("Cora is your coordinator.")).toBeInTheDocument();
    expect(document.querySelector("time")).toHaveAttribute("datetime", "2026-09-28T01:00:00Z");
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
    client.setQueryData(["notifications", 1], [note({ message: "Private message" })]);
    renderNotifications(2, client);
    await userEvent.click(screen.getByText("Notifications (0)"));
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
    expect(screen.queryByText("Private message")).not.toBeInTheDocument();
  });
});

describe("SCRUM-82 notification centre", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getUnreadCount).mockResolvedValue({ unread: 0 });
  });

  it("AC1: lists notifications newest first with the unread count in the header button", async () => {
    vi.mocked(listNotifications).mockResolvedValue([
      note({ id: 1, message: "Older message", created_at: "2026-09-20T01:00:00Z" }),
      note({ id: 2, message: "Newer message", created_at: "2026-09-29T01:00:00Z" }),
    ]);
    vi.mocked(getUnreadCount).mockResolvedValue({ unread: 2 });
    renderNotifications();
    await userEvent.click(await screen.findByText("Notifications (2)"));
    const items = within(await screen.findByRole("list", { name: "Notifications" })).getAllByRole(
      "listitem",
    );
    expect(items[0]).toHaveTextContent("Newer message");
    expect(items[1]).toHaveTextContent("Older message");
  });

  it("AC2/AC3: clicking an unread notification marks it read, drops the count and opens its event", async () => {
    vi.mocked(listNotifications).mockResolvedValue([note()]);
    vi.mocked(getUnreadCount).mockResolvedValue({ unread: 1 });
    vi.mocked(markNotificationRead).mockResolvedValue({
      ...note({ read_at: "2026-09-29T01:00:00Z", is_read: true }),
      unread: 0,
    });
    const { client } = renderNotifications();
    await userEvent.click(await screen.findByText("Notifications (1)"));
    await userEvent.click(await screen.findByRole("link", { name: /Cora is your coordinator/ }));
    expect(markNotificationRead).toHaveBeenCalledWith(1);
    expect(await screen.findByText("Organiser event page")).toBeInTheDocument();
    await vi.waitFor(() =>
      expect(client.getQueryData(["notifications", 1, "unread"])).toEqual({ unread: 0 }),
    );
  });

  it("AC2: a notification that is already read is not marked again", async () => {
    vi.mocked(listNotifications).mockResolvedValue([
      note({ read_at: "2026-09-29T01:00:00Z", is_read: true }),
    ]);
    renderNotifications(1, undefined, "ATTENDEE");
    await userEvent.click(await screen.findByText("Notifications (0)"));
    await userEvent.click(await screen.findByRole("link", { name: /Cora is your coordinator/ }));
    expect(markNotificationRead).not.toHaveBeenCalled();
    // AC3 - an attendee is taken to their registrations.
    expect(await screen.findByText("My registrations page")).toBeInTheDocument();
  });

  it("AC4: shows an empty state, not an error", async () => {
    vi.mocked(listNotifications).mockResolvedValue([]);
    renderNotifications();
    await userEvent.click(screen.getByText("Notifications (0)"));
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("SCRUM-79 AC5: shows the event name, what happened and when", async () => {
    vi.mocked(listNotifications).mockResolvedValue([note()]);
    renderNotifications();
    await userEvent.click(screen.getByText(/^Notifications \(/));
    const link = await screen.findByRole("link", { name: /Cora is your coordinator/ });
    expect(link).toHaveTextContent("Partner Summit · Coordinator assigned");
    expect(
      screen.getByText(new Date("2026-09-28T01:00:00Z").toLocaleString("en-SG")),
    ).toBeInTheDocument();
  });
});

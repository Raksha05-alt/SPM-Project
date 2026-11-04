import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listAttendeeEvents } from "../api/events";
import { AttendeeEvents } from "./AttendeeEvents";

vi.mock("../api/events", () => ({ listAttendeeEvents: vi.fn() }));
// SCRUM-21 - the page also shows registration; its own tests are in components/registrations.
vi.mock("../api/registrations", () => ({
  listMyRegistrations: vi.fn().mockResolvedValue([]),
  getRegistrationSummary: vi.fn().mockResolvedValue({ open: false, reason: "", my_status: null }),
}));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: null }) }));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AttendeeEvents />
    </QueryClientProvider>,
  );
}

describe("AttendeeEvents", () => {
  beforeEach(() => vi.clearAllMocks());

  it("US-06.1 AC2-AC4: shows only the attendee-safe status details returned by the API", async () => {
    vi.mocked(listAttendeeEvents).mockResolvedValue([
      {
        id: 42,
        name: "Regional Partner Conference",
        description: "A public partner conference.",
        preferred_start: "2026-10-20T01:00:00Z",
        preferred_end: "2026-10-20T07:00:00Z",
        accessibility_needs: "Step-free access",
        registration_required: true,
        status: "CONFIRMED",
        status_label: "Confirmed",
        status_description: "All essential arrangements are in place.",
        status_changed_at: "2026-09-22T02:00:00Z",
      },
    ]);

    renderPage();

    expect(await screen.findByText("Regional Partner Conference")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toHaveAttribute(
      "title",
      "All essential arrangements are in place.",
    );
    expect(screen.getByText("All essential arrangements are in place.")).toBeInTheDocument();
    expect(screen.getByText(/Status updated/)).toBeInTheDocument();
  });
});

it("SCRUM-87 AC6: shows every confirmed session with its own room and period", async () => {
  vi.mocked(listAttendeeEvents).mockResolvedValue([{ id: 87, name: "Parallel conference", description: "",
    preferred_start: "2027-06-08T02:00:00Z", preferred_end: "2027-06-08T04:00:00Z",
    accessibility_needs: "", registration_required: false, status: "CONFIRMED", status_label: "Confirmed",
    status_description: "All essential arrangements are in place.", status_changed_at: null,
    venues: [
      { session_name: "Main programme", venue: "Main Hall", location: "Level 1", starts_at: "2027-06-08T02:00:00Z", ends_at: "2027-06-08T04:00:00Z" },
      { session_name: "Breakout A", venue: "Workshop", location: "Level 2", starts_at: "2027-06-08T03:00:00Z", ends_at: "2027-06-08T04:00:00Z" },
    ],
  }]);
  renderPage();
  expect(await screen.findByRole("list", { name: "Event sessions" })).toHaveTextContent("Main programme: Main Hall, Level 1");
  expect(screen.getByRole("list", { name: "Event sessions" })).toHaveTextContent("Breakout A: Workshop, Level 2");
  expect(screen.queryByText(/Safety Officer|decision reason/i)).not.toBeInTheDocument();
});

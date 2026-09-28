import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listAttendeeEvents } from "../api/events";
import { AttendeeEvents } from "./AttendeeEvents";

vi.mock("../api/events", () => ({ listAttendeeEvents: vi.fn() }));

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

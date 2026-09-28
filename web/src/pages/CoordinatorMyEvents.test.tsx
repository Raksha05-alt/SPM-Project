import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchMyEvents } from "../api/events";
import { CoordinatorMyEvents } from "./CoordinatorMyEvents";

vi.mock("../api/events", () => ({ fetchMyEvents: vi.fn() }));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CoordinatorMyEvents />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CoordinatorMyEvents", () => {
  beforeEach(() => vi.clearAllMocks());

  it("SCRUM-54 AC1: shows each event with its status and next required action", async () => {
    vi.mocked(fetchMyEvents).mockResolvedValue([
      {
        id: 3,
        name: "Partner Summit",
        organisation_name: "Acme Pte Ltd",
        preferred_start: "2026-10-20T01:00:00Z",
        expected_attendance: 80,
        status: "SUBMITTED",
        status_label: "Submitted",
        status_description: "Sent to ConnectSphere for review.",
        submitted_at: "2026-09-22T01:00:00Z",
        coordinator_name: "Cora Coordinator",
        assignment_requires_attention: false,
        next_action: "Review the request and approve, reject or ask for detail.",
        requires_action: true,
      },
    ]);

    renderPage();

    expect(await screen.findByText("Partner Summit")).toBeInTheDocument();
    expect(screen.getByTitle("Sent to ConnectSphere for review.")).toHaveTextContent("Submitted");
    expect(
      screen.getByText("Review the request and approve, reject or ask for detail."),
    ).toBeInTheDocument();
    expect(screen.getByText("Action needed")).toBeInTheDocument();
  });

  it("SCRUM-54 AC3: shows an empty state rather than an error", async () => {
    vi.mocked(fetchMyEvents).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("You have no assigned events right now.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchQueue } from "../api/events";
import { CoordinatorQueue } from "./CoordinatorQueue";

vi.mock("../api/events", () => ({ fetchQueue: vi.fn() }));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CoordinatorQueue />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CoordinatorQueue", () => {
  beforeEach(() => vi.clearAllMocks());

  it("US-04.1 AC1: exposes the status explanation with each queue item", async () => {
    vi.mocked(fetchQueue).mockResolvedValue([
      {
        id: 7,
        name: "Annual Conference",
        organisation_name: "Acme Pte Ltd",
        preferred_start: "2026-10-20T01:00:00Z",
        expected_attendance: 120,
        status: "SUBMITTED",
        status_label: "Submitted",
        status_description: "Sent to ConnectSphere for review.",
        submitted_at: "2026-09-22T01:00:00Z",
        coordinator: null,
        coordinator_name: null,
        assignment_requires_attention: true,
        approved_by_name: null,
        approved_at: null,
      },
    ]);

    renderPage();

    expect(await screen.findByText("Annual Conference")).toBeInTheDocument();
    expect(screen.getByTitle("Sent to ConnectSphere for review.")).toHaveTextContent("Submitted");
    expect(screen.getByText("Unassigned — staff action needed")).toBeInTheDocument();
  });
});

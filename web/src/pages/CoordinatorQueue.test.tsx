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

it("SCRUM-47 AC5 distinguishes an empty queue from a failed load", async () => {
  vi.mocked(fetchQueue).mockResolvedValue([]);
  const empty = renderPage();
  expect(await screen.findByText(/Nothing is waiting/)).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  empty.unmount();
  vi.mocked(fetchQueue).mockRejectedValue(new Error("offline"));
  renderPage();
  expect(await screen.findByRole("alert")).toHaveTextContent("We could not load the queue.");
  expect(screen.queryByText(/Nothing is waiting/)).not.toBeInTheDocument();
});

it("US-47 displays incomplete imported dates and assignment details without an invalid date", async () => {
  vi.mocked(fetchQueue).mockResolvedValue([{
    id: 8, name: "Imported request", organisation_name: "Acme",
    preferred_start: null, expected_attendance: null, submitted_at: null,
    status: "SUBMITTED", status_label: "Submitted", status_description: "Awaiting review",
    coordinator: null, coordinator_name: null, assignment_requires_attention: false,
    approved_by_name: null, approved_at: null,
  }]);
  renderPage();
  expect(await screen.findByRole("link", { name: "Imported request" })).toHaveAttribute("href", "/coordinator/events/8");
  expect(screen.getAllByRole("cell", { name: "—" })).toHaveLength(3);
  expect(screen.getByText("Not assigned")).toBeVisible();
  expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument();
});

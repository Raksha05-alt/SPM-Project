import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchQueueByStatus } from "../api/planning";
import type { QueueRow } from "../types";
import { CoordinatorQueue } from "./CoordinatorQueue";

vi.mock("../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/planning")>()),
  fetchQueueByStatus: vi.fn(),
}));

function row(overrides: Partial<QueueRow> = {}): QueueRow {
  return {
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
    ...overrides,
  };
}

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
    vi.mocked(fetchQueueByStatus).mockResolvedValue([row()]);

    renderPage();

    expect(await screen.findByText("Annual Conference")).toBeInTheDocument();
    expect(screen.getByTitle("Sent to ConnectSphere for review.")).toHaveTextContent("Submitted");
    expect(screen.getByText("Unassigned — staff action needed")).toBeInTheDocument();
  });
});

describe("SCRUM-57 filter the queue by status", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: filters by one status", async () => {
    vi.mocked(fetchQueueByStatus).mockImplementation(async (statuses) =>
      statuses.includes("PLANNING")
        ? [row({ id: 8, name: "Planning Day", status: "PLANNING", status_label: "Planning" })]
        : [row()],
    );

    renderPage();
    expect(await screen.findByText("Annual Conference")).toBeInTheDocument();
    expect(fetchQueueByStatus).toHaveBeenCalledWith([]);

    await userEvent.click(screen.getByLabelText("Planning"));

    expect(await screen.findByText("Planning Day")).toBeInTheDocument();
    expect(fetchQueueByStatus).toHaveBeenLastCalledWith(["PLANNING"]);
    expect(screen.queryByText("Annual Conference")).not.toBeInTheDocument();
  });

  it("AC2: filters by several statuses at once and can be cleared", async () => {
    vi.mocked(fetchQueueByStatus).mockResolvedValue([row()]);

    renderPage();
    await screen.findByText("Annual Conference");
    await userEvent.click(screen.getByLabelText("Approved"));
    await userEvent.click(screen.getByLabelText("Confirmed"));

    expect(fetchQueueByStatus).toHaveBeenLastCalledWith(["APPROVED", "CONFIRMED"]);

    await userEvent.click(screen.getByRole("button", { name: "Clear filter" }));
    expect(fetchQueueByStatus).toHaveBeenLastCalledWith([]);
  });

  it("AC4: says when nothing matches the selected statuses", async () => {
    vi.mocked(fetchQueueByStatus).mockImplementation(async (statuses) =>
      statuses.length ? [] : [row()],
    );

    renderPage();
    await screen.findByText("Annual Conference");
    await userEvent.click(screen.getByLabelText("Cancelled"));

    expect(await screen.findByText("No events match the selected statuses.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

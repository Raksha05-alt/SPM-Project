import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { approveEvent } from "../api/events";
import { fetchMyEventsByStatus } from "../api/planning";
import { ApiError } from "../api/client";
import type { AssignedEventRow, EventRequest } from "../types";
import { CoordinatorMyEvents } from "./CoordinatorMyEvents";

vi.mock("../api/events", () => ({ approveEvent: vi.fn() }));
vi.mock("../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/planning")>()),
  fetchMyEventsByStatus: vi.fn(),
}));

function row(overrides: Partial<AssignedEventRow> = {}): AssignedEventRow {
  return {
    id: 3,
    name: "Partner Summit",
    organisation_name: "Acme Pte Ltd",
    preferred_start: "2026-10-20T01:00:00Z",
    expected_attendance: 80,
    status: "SUBMITTED",
    status_label: "Submitted",
    status_description: "Sent to ConnectSphere for review.",
    submitted_at: "2026-09-22T01:00:00Z",
    coordinator: 2,
    coordinator_name: "Cora Coordinator",
    assignment_requires_attention: false,
    approved_by_name: null,
    approved_at: null,
    next_action: "Review the request and approve, reject or ask for detail.",
    requires_action: true,
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
        <CoordinatorMyEvents />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CoordinatorMyEvents", () => {
  beforeEach(() => vi.clearAllMocks());

  it("SCRUM-54 AC1: shows each event with its status and next required action", async () => {
    vi.mocked(fetchMyEventsByStatus).mockResolvedValue([row()]);

    renderPage();

    expect(await screen.findByText("Partner Summit")).toBeInTheDocument();
    expect(screen.getByTitle("Sent to ConnectSphere for review.")).toHaveTextContent("Submitted");
    expect(
      screen.getByText("Review the request and approve, reject or ask for detail."),
    ).toBeInTheDocument();
    expect(screen.getByText("Action needed")).toBeInTheDocument();
  });

  it("SCRUM-54 AC3: shows an empty state rather than an error", async () => {
    vi.mocked(fetchMyEventsByStatus).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("You have no assigned events right now.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("Approve AC1: approving a submitted request calls the API and refreshes the list", async () => {
    vi.mocked(fetchMyEventsByStatus).mockResolvedValue([row()]);
    vi.mocked(approveEvent).mockResolvedValue({} as EventRequest);

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Approve Partner Summit" }));

    expect(approveEvent).toHaveBeenCalledWith(3);
    expect(fetchMyEventsByStatus).toHaveBeenCalledTimes(2);
  });

  it("Approve AC2: shows who approved the request and when", async () => {
    vi.mocked(fetchMyEventsByStatus).mockResolvedValue([
      row({
        status: "APPROVED",
        status_label: "Approved",
        approved_by_name: "Cora Coordinator",
        approved_at: "2026-09-25T02:00:00Z",
        requires_action: true,
      }),
    ]);

    renderPage();

    expect(await screen.findByText(/Approved by Cora Coordinator/)).toBeInTheDocument();
  });

  it("Approve AC3: offers no Approve button outside a reviewable status", async () => {
    vi.mocked(fetchMyEventsByStatus).mockResolvedValue([
      row({ status: "PLANNING", status_label: "Planning" }),
    ]);

    renderPage();

    expect(await screen.findByText("Partner Summit")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("Approve AC3/AC4: shows the reason when the API refuses", async () => {
    vi.mocked(fetchMyEventsByStatus).mockResolvedValue([row()]);
    vi.mocked(approveEvent).mockRejectedValue(
      new ApiError(403, null, "Only the coordinator assigned to this event can approve it."),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Approve Partner Summit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only the coordinator assigned to this event can approve it.",
    );
  });
});

describe("SCRUM-57 filter my events by status", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1/AC2: requests only the chosen statuses, one or several", async () => {
    vi.mocked(fetchMyEventsByStatus).mockImplementation(async (statuses) =>
      statuses.length
        ? [row({ id: 4, name: "Planning Day", status: "PLANNING", status_label: "Planning" })]
        : [row()],
    );

    renderPage();
    await screen.findByText("Partner Summit");
    await userEvent.click(screen.getByLabelText("Planning"));

    expect(await screen.findByText("Planning Day")).toBeInTheDocument();
    expect(fetchMyEventsByStatus).toHaveBeenLastCalledWith(["PLANNING"]);

    await userEvent.click(screen.getByLabelText("Confirmed"));
    expect(fetchMyEventsByStatus).toHaveBeenLastCalledWith(["PLANNING", "CONFIRMED"]);
  });

  it("AC4: says when nothing matches the filter", async () => {
    vi.mocked(fetchMyEventsByStatus).mockImplementation(async (statuses) =>
      statuses.length ? [] : [row()],
    );

    renderPage();
    await screen.findByText("Partner Summit");
    await userEvent.click(screen.getByLabelText("Rejected"));

    expect(await screen.findByText("No events match the selected statuses.")).toBeInTheDocument();
  });
});

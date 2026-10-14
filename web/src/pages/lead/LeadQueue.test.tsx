import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  assignCoordinator,
  fetchAssignments,
  fetchUnassigned,
  listCoordinatorOptions,
  type AssignmentRow,
} from "../../api/lead";
import { planningEvent } from "../../components/planning/fixtures";
import type { QueueRow } from "../../types";
import { LeadAssignments } from "./LeadAssignments";
import { LeadQueue } from "./LeadQueue";

vi.mock("../../api/lead", () => ({
  fetchUnassigned: vi.fn(),
  fetchAssignments: vi.fn(),
  listCoordinatorOptions: vi.fn(),
  assignCoordinator: vi.fn(),
}));

function row(overrides: Partial<QueueRow> = {}): QueueRow {
  return {
    id: 7,
    name: "Partner Summit",
    organisation_name: "Acme Pte Ltd",
    preferred_start: "2026-11-20T01:00:00Z",
    expected_attendance: 120,
    status: "SUBMITTED",
    status_label: "Submitted",
    status_description: "",
    submitted_at: "2026-10-01T01:00:00Z",
    coordinator: null,
    coordinator_name: null,
    assignment_requires_attention: true,
    approved_by_name: null,
    approved_at: null,
    ...overrides,
  };
}

function renderWith(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCoordinatorOptions).mockResolvedValue([
    { id: 2, name: "Cora Coordinator", email: "cora@x", available: true, active_events: 3 },
    { id: 5, name: "Dan Delegate", email: "dan@x", available: false, active_events: 0 },
  ]);
});

describe("Week 7 CR5 - the Lead's unassigned queue", () => {
  it("AC2: lists the requests waiting for a coordinator", async () => {
    vi.mocked(fetchUnassigned).mockResolvedValue([row()]);

    renderWith(<LeadQueue />);

    expect(await screen.findByRole("link", { name: "Partner Summit" })).toHaveAttribute(
      "href",
      "/lead/events/7",
    );
    expect(screen.getByText("Acme Pte Ltd")).toBeInTheDocument();
  });

  it("AC2: an empty queue is a message, not an error", async () => {
    vi.mocked(fetchUnassigned).mockResolvedValue([]);

    renderWith(<LeadQueue />);

    expect(
      await screen.findByText("Every submitted request has a coordinator."),
    ).toBeInTheDocument();
  });

  it("AC3: the Lead sees availability and workload and assigns a coordinator", async () => {
    vi.mocked(fetchUnassigned).mockResolvedValue([row()]);
    vi.mocked(assignCoordinator).mockResolvedValue(planningEvent({ coordinator: 2 }));

    renderWith(<LeadQueue />);
    await screen.findByRole("option", { name: "Cora Coordinator · 3 active" });
    expect(
      screen.getByRole("option", { name: "Dan Delegate · 0 active · unavailable" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign Partner Summit" })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Coordinator for Partner Summit"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Assign Partner Summit" }));

    expect(assignCoordinator).toHaveBeenCalledWith(7, 2);
  });

  it("AC3: shows the API's refusal", async () => {
    vi.mocked(fetchUnassigned).mockResolvedValue([row()]);
    vi.mocked(assignCoordinator).mockRejectedValue(
      new ApiError(400, {}, "Choose an active Event Coordinator."),
    );

    renderWith(<LeadQueue />);
    await screen.findByRole("option", { name: "Cora Coordinator · 3 active" });
    await userEvent.selectOptions(screen.getByLabelText("Coordinator for Partner Summit"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Assign Partner Summit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose an active Event Coordinator.",
    );
  });
});

describe("Week 7 CR5 - all assignments", () => {
  function assignment(overrides: Partial<AssignmentRow> = {}): AssignmentRow {
    return {
      ...row({ id: 8, status: "PLANNING", status_label: "Planning", coordinator: 2 }),
      coordinator_name: "Cora Coordinator",
      coordinator_email: "cora@x",
      assigned_by: 1,
      assigned_by_name: "Leah Lead",
      assigned_at: "2026-10-02T01:00:00Z",
      ...overrides,
    };
  }

  it("AC6: shows every active assignment and who made it", async () => {
    vi.mocked(fetchAssignments).mockResolvedValue([assignment()]);

    renderWith(<LeadAssignments />);

    expect(await screen.findByText("Leah Lead")).toBeInTheDocument();
    expect(screen.getByText("cora@x")).toBeInTheDocument();
    expect(fetchAssignments).toHaveBeenCalledWith(false);
  });

  it("AC6: narrows to the assignments the Lead supervises", async () => {
    vi.mocked(fetchAssignments).mockResolvedValue([assignment()]);

    renderWith(<LeadAssignments />);
    await userEvent.click(await screen.findByLabelText(/Only events I assigned/));

    expect(fetchAssignments).toHaveBeenLastCalledWith(true);
  });

  it("AC4: reassigns to someone other than the current coordinator", async () => {
    vi.mocked(fetchAssignments).mockResolvedValue([assignment()]);
    vi.mocked(assignCoordinator).mockResolvedValue(planningEvent({ coordinator: 5 }));

    renderWith(<LeadAssignments />);
    await screen.findByRole("option", { name: /Dan Delegate/ });
    expect(screen.queryByRole("option", { name: /Cora Coordinator/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Coordinator for Partner Summit"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Reassign Partner Summit" }));

    expect(assignCoordinator).toHaveBeenCalledWith(8, 5);
  });

  it("says when there is nothing to show", async () => {
    vi.mocked(fetchAssignments).mockResolvedValue([]);

    renderWith(<LeadAssignments />);

    expect(await screen.findByText("No active assignments.")).toBeInTheDocument();
  });
});

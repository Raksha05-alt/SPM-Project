import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api/leadAssignments";
import { ApiError } from "../../api/client";
import { LeadDashboard } from "./LeadDashboard";
import { LeadEventDetail } from "./LeadEventDetail";

vi.mock("../../api/leadAssignments");
vi.mock("../../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: 7 } }) }));

const initial = {
  id: 9, name: "Partner Summit", purpose: "Annual briefing", organisation_name: "Acme",
  preferred_start: null, preferred_end: null, expected_attendance: 60,
  status: "SUBMITTED", status_label: "Submitted", coordinator: null, coordinator_name: null,
  coordinator_email: null, supervising_lead: null, supervising_lead_name: null,
  assignment_revision: 0, assignment_history: [], can_assign: true,
} as unknown as api.LeadEvent;
const assigned: api.LeadEvent = {
  ...initial, coordinator: 2, coordinator_name: "Cora", coordinator_email: "cora@example.com",
  supervising_lead: 7, supervising_lead_name: "Lee", assignment_revision: 1,
  assignment_history: [{ id: 1, revision: 1, previous_coordinator: null,
    previous_coordinator_name: null, coordinator: 2, coordinator_name: "Cora",
    assigned_by: 7, assigned_by_name: "Lee", previous_supervising_lead: null,
    previous_supervising_lead_name: null, assigned_at: "2026-10-26T07:00:00Z" }],
};

function show(detail = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[detail ? "/lead/events/9" : "/lead"]}>
    <Routes><Route path="/lead" element={<LeadDashboard />} /><Route path="/lead/events/:id" element={<LeadEventDetail />} /></Routes>
  </MemoryRouter></QueryClientProvider>);
}

describe("SCRUM-89 / SCRUM-53 Lead assignments", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.getLeadEvent).mockResolvedValue(initial);
    vi.mocked(api.listCoordinators).mockResolvedValue([
      { id: 2, name: "Cora", email: "cora@example.com", coordinator_available: false },
      { id: 3, name: "Casey", email: "casey@example.com", coordinator_available: true },
    ]);
    vi.mocked(api.listUnassignedEvents).mockResolvedValue([initial]);
    vi.mocked(api.listAssignments).mockResolvedValue([]);
  });

  it("AC2/6: renders allocation and applies supervisor and closed-event filters", async () => {
    const user = userEvent.setup();
    show();
    expect(await screen.findByRole("link", { name: "Partner Summit" })).toHaveAttribute("href", "/lead/events/9");
    await user.click(screen.getByRole("button", { name: /^Assignments$/ }));
    expect(await screen.findByText("No events match these filters.")).toBeVisible();
    await user.click(screen.getByLabelText("Only events I supervise"));
    await waitFor(() => expect(api.listAssignments).toHaveBeenLastCalledWith(true, true));
    await user.click(screen.getByLabelText("Active events only"));
    await waitFor(() => expect(api.listAssignments).toHaveBeenLastCalledWith(true, false));
    await user.click(screen.getByRole("button", { name: "Unassigned requests" }));
    expect(await screen.findByRole("link", { name: "Partner Summit" })).toBeVisible();
  });

  it("renders known dates and missing attendance in the allocation table", async () => {
    vi.mocked(api.listUnassignedEvents).mockResolvedValue([{ ...initial, preferred_start: "2026-10-26T08:00:00Z", expected_attendance: null }]);
    show();
    await screen.findByRole("link", { name: "Partner Summit" });
    expect(screen.getAllByText("Not recorded")).toHaveLength(2);
    expect(screen.getByRole("table")).toHaveTextContent("2026");
  });

  it("retries event loading and renders the recorded period and missing attendance", async () => {
    vi.mocked(api.getLeadEvent).mockRejectedValueOnce(new Error("offline")).mockResolvedValue({
      ...initial, preferred_start: "2026-10-26T08:00:00Z", preferred_end: "2026-10-26T12:00:00Z", expected_attendance: null,
    });
    show(true);
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByLabelText("Event Coordinator");
    expect(screen.getByText(/Unrecorded attending/)).toHaveTextContent("2026");
  });

  it("AC2: can recover a failed queue load and show an empty queue", async () => {
    vi.mocked(api.listUnassignedEvents).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([]);
    show();
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No unassigned requests.")).toBeVisible();
  });

  it("AC3/7: requires a selection, sends the revision and shows saved contact/history", async () => {
    show(true);
    const select = await screen.findByLabelText("Event Coordinator");
    expect(screen.getByRole("button", { name: "Assign coordinator" })).toBeDisabled();
    expect(screen.getByRole("option", { name: /Cora.*marked unavailable/ })).toBeInTheDocument();
    await userEvent.selectOptions(select, "2");
    vi.mocked(api.assignCoordinator).mockResolvedValue(assigned);
    vi.mocked(api.getLeadEvent).mockResolvedValue(assigned);
    await userEvent.click(screen.getByRole("button", { name: "Assign coordinator" }));
    await waitFor(() => expect(api.assignCoordinator).toHaveBeenCalledWith(9, 2, 0));
    expect(await screen.findByText("Coordinator assignment saved.")).toBeVisible();
    expect(screen.getByRole("region", { name: "Current assignment" })).toHaveTextContent("cora@example.com");
    expect(screen.getByRole("region", { name: "Assignment history" })).toHaveTextContent("Unassigned → Cora");
    expect(screen.getByRole("button", { name: "Reassign coordinator" })).toBeDisabled();
  });

  it("AC4: reassigns using the current revision", async () => {
    vi.mocked(api.getLeadEvent).mockResolvedValue(assigned);
    vi.mocked(api.assignCoordinator).mockResolvedValue({ ...assigned, coordinator: 3, assignment_revision: 2 });
    show(true);
    await userEvent.selectOptions(await screen.findByLabelText("Event Coordinator"), "2");
    expect(screen.getByRole("button", { name: "Reassign coordinator" })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Event Coordinator"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Reassign coordinator" }));
    await waitFor(() => expect(api.assignCoordinator).toHaveBeenCalledWith(9, 3, 1));
  });

  it.each(["COMPLETED", "CANCELLED"] as const)("AC4: %s hides allocation controls", async status => {
    vi.mocked(api.getLeadEvent).mockResolvedValue({ ...assigned, status, can_assign: false });
    show(true);
    await screen.findByRole("heading", { name: "Partner Summit" });
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(api.listCoordinators).not.toHaveBeenCalled();
  });

  it("AC3: explains when no active coordinators exist", async () => {
    vi.mocked(api.listCoordinators).mockResolvedValue([]);
    show(true);
    expect(await screen.findByText("No active coordinator accounts are available.")).toBeVisible();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  it("AC3: recovers coordinator list errors", async () => {
    vi.mocked(api.listCoordinators).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([]);
    show(true);
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No active coordinator accounts are available.")).toBeVisible();
  });

  it("refuses to render stale event data when the detail refresh fails", async () => {
    vi.mocked(api.getLeadEvent).mockRejectedValue(new ApiError(403, {}, "Forbidden"));
    show(true);
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load this event.");
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  it.each([true, false])("reloads after a conflicting or unconfirmed save (conflict=%s)", async conflict => {
    show(true);
    await userEvent.selectOptions(await screen.findByLabelText("Event Coordinator"), "2");
    vi.mocked(api.assignCoordinator).mockRejectedValue(conflict ? new ApiError(409, {}, "The assignment changed. Reload the event before assigning it.") : new Error("network lost"));
    vi.mocked(api.getLeadEvent).mockResolvedValue(assigned);
    await userEvent.click(screen.getByRole("button", { name: "Assign coordinator" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(conflict ? "The assignment changed." : "We could not confirm the save.");
    await waitFor(() => expect(screen.getByRole("region", { name: "Current assignment" })).toHaveTextContent("cora@example.com"));
    expect(screen.getByRole("button", { name: "Reassign coordinator" })).toBeDisabled();
  });
});

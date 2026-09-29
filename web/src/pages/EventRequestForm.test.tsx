import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getEvent, submitEvent, updateDraft } from "../api/events";
import type { EventRequest } from "../types";
import { EventRequestForm } from "./EventRequestForm";

vi.mock("../api/events", () => ({
  getEvent: vi.fn(),
  createDraft: vi.fn(),
  updateDraft: vi.fn(),
  submitEvent: vi.fn(),
}));

function awaitingClarification(): EventRequest {
  return {
    id: 4,
    name: "Partner Summit",
    purpose: "Annual partner briefing",
    description: "",
    preferred_start: "2026-10-20T01:00:00Z",
    preferred_end: "2026-10-20T07:00:00Z",
    expected_attendance: 120,
    required_layout: "",
    accessibility_needs: "",
    equipment_notes: "",
    registration_required: false,
    status: "UNDER_REVIEW",
    status_label: "Awaiting Clarification",
    status_description: "A coordinator has asked the client for more information.",
    status_changed_at: "2026-09-28T01:00:00Z",
    submitted_at: "2026-09-22T01:00:00Z",
    organisation_name: "Acme Pte Ltd",
    created_by_name: "Ada Organiser",
    coordinator: 2,
    coordinator_name: "Cora Coordinator",
    coordinator_email: "coordinator@connectsphere.example",
    assignment_requires_attention: false,
    rejection_reason: "",
    rejected_at: null,
    clarifications: [
      {
        id: 1,
        message: "How many wheelchair users are attending?",
        fields: ["accessibility_needs"],
        requested_by_name: "Cora Coordinator",
        requested_at: "2026-09-28T01:00:00Z",
        resolved_at: null,
      },
    ],
    missing_mandatory_fields: [],
    is_editable: true,
    created_at: "2026-09-21T01:00:00Z",
    updated_at: "2026-09-28T01:00:00Z",
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/organiser/requests/4"]}>
        <Routes>
          <Route path="/organiser/requests/:id" element={<EventRequestForm />} />
          <Route path="/organiser" element={<p>Dashboard</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EventRequestForm awaiting clarification", () => {
  beforeEach(() => vi.clearAllMocks());

  it("SCRUM-49 AC2: shows what the coordinator needs and lets the organiser edit and resubmit", async () => {
    vi.mocked(getEvent).mockResolvedValue(awaitingClarification());
    vi.mocked(updateDraft).mockResolvedValue(awaitingClarification());
    vi.mocked(submitEvent).mockResolvedValue({
      ...awaitingClarification(),
      status: "SUBMITTED",
    });

    renderPage();

    expect(
      await screen.findByText("How many wheelchair users are attending?", {
        selector: "div[role=alert] p",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Please check: Accessibility needs")).toBeInTheDocument();

    const accessibility = screen.getByLabelText("Accessibility needs");
    expect(accessibility).toBeEnabled();
    await userEvent.type(accessibility, "Six wheelchair users");
    await userEvent.click(screen.getByRole("button", { name: "Resubmit to ConnectSphere" }));

    expect(updateDraft).toHaveBeenCalledWith(
      4,
      expect.objectContaining({ accessibility_needs: "Six wheelchair users" }),
    );
    expect(submitEvent).toHaveBeenCalledWith(4);
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
  });

  it("SCRUM-49 AC3: shows the clarification history", async () => {
    vi.mocked(getEvent).mockResolvedValue(awaitingClarification());

    renderPage();

    expect(await screen.findByText("Clarification history")).toBeInTheDocument();
    expect(screen.getByText(/Asked by Cora Coordinator/)).toBeInTheDocument();
  });

  it("SCRUM-52 AC3: shows the rejection decision, reason and date, read-only", async () => {
    vi.mocked(getEvent).mockResolvedValue({
      ...awaitingClarification(),
      status: "REJECTED",
      status_label: "Rejected",
      status_description: "ConnectSphere is not able to support this request.",
      rejection_reason: "Venue unavailable for 500 people.",
      rejected_at: "2026-09-29T03:00:00Z",
      is_editable: false,
      clarifications: [],
    });

    renderPage();

    expect(
      await screen.findByText("Reason: Venue unavailable for 500 people."),
    ).toBeInTheDocument();
    expect(screen.getByText(/^Decided /)).toBeInTheDocument();
    expect(screen.getByLabelText("Event name")).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /Resubmit|Send to ConnectSphere/ }),
    ).not.toBeInTheDocument();
  });
});

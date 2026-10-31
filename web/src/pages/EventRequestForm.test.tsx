import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { addClarificationNote, getEvent, submitEvent, updateDraft } from "../api/events";
import type { EventRequest } from "../types";
import { EventRequestForm } from "./EventRequestForm";

vi.mock("../api/events", () => ({
  getEvent: vi.fn(),
  createDraft: vi.fn(),
  updateDraft: vi.fn(),
  submitEvent: vi.fn(),
  addClarificationNote: vi.fn(),
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
        comments: [],
      },
    ],
    missing_mandatory_fields: [],
    // SCRUM-61 AC6 / SCRUM-92 AC3 - not editable by the client after submission.
    is_editable: false,
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

  it("SCRUM-92 AC3: shows what the coordinator needs, but the client cannot edit or resubmit", async () => {
    // Replaces the SCRUM-49 organiser edit-and-resubmit test (kept in Git history).
    vi.mocked(getEvent).mockResolvedValue(awaitingClarification());

    renderPage();

    expect(
      await screen.findByText("How many wheelchair users are attending?", {
        selector: "div[role=alert] p",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Please check: Accessibility needs")).toBeInTheDocument();
    expect(screen.getByLabelText("Accessibility needs")).toBeDisabled();
    expect(
      screen.queryByRole("button", {
        name: /Resubmit|Send to ConnectSphere|Save draft|Save changes/,
      }),
    ).not.toBeInTheDocument();
    expect(updateDraft).not.toHaveBeenCalled();
    expect(submitEvent).not.toHaveBeenCalled();
  });

  it("SCRUM-92 AC1: the client records a note from the offline conversation", async () => {
    vi.mocked(getEvent).mockResolvedValue(awaitingClarification());
    vi.mocked(addClarificationNote).mockResolvedValue(awaitingClarification());

    renderPage();
    await userEvent.type(
      await screen.findByLabelText("Add a note from your conversation"),
      "Agreed by phone: six wheelchair users.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));

    expect(addClarificationNote).toHaveBeenCalledWith(4, "Agreed by phone: six wheelchair users.");
  });

  it("SCRUM-92 AC2: an empty note is not sent", async () => {
    vi.mocked(getEvent).mockResolvedValue(awaitingClarification());

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Save note" }));

    expect(screen.getByText("Write the note before saving it.")).toBeInTheDocument();
    expect(addClarificationNote).not.toHaveBeenCalled();
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

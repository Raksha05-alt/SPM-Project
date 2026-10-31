import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  addClarificationNote,
  approveEvent,
  getEvent,
  rejectEvent,
  requestClarification,
  resumeReview,
  updateEvent,
} from "../api/events";
import { ApiError } from "../api/client";
import type { EventRequest } from "../types";
import { CoordinatorEventDetail } from "./CoordinatorEventDetail";

vi.mock("../api/events", () => ({
  getEvent: vi.fn(),
  approveEvent: vi.fn(),
  requestClarification: vi.fn(),
  rejectEvent: vi.fn(),
  resumeReview: vi.fn(),
  updateEvent: vi.fn(),
  addClarificationNote: vi.fn(),
}));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: 2 } }) }));

function event(overrides: Partial<EventRequest> = {}): EventRequest {
  return {
    id: 9,
    name: "Partner Summit",
    purpose: "Annual partner briefing",
    description: "Keynote and breakout sessions.",
    preferred_start: "2026-10-20T01:00:00Z",
    preferred_end: "2026-10-20T07:00:00Z",
    expected_attendance: 120,
    required_layout: "THEATRE",
    accessibility_needs: "Wheelchair access",
    equipment_notes: "Two projectors",
    registration_required: true,
    status: "SUBMITTED",
    status_label: "Submitted",
    status_description: "Sent to ConnectSphere for review.",
    status_changed_at: "2026-09-22T01:00:00Z",
    submitted_at: "2026-09-22T01:00:00Z",
    organisation_name: "Acme Pte Ltd",
    created_by_name: "Ada Organiser",
    coordinator: 2,
    coordinator_name: "Cora Coordinator",
    coordinator_email: "coordinator@connectsphere.example",
    assignment_requires_attention: false,
    approved_by_name: null,
    approved_at: null,
    rejection_reason: "",
    rejected_at: null,
    clarifications: [],
    missing_mandatory_fields: [],
    is_editable: false,
    created_at: "2026-09-21T01:00:00Z",
    updated_at: "2026-09-22T01:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/coordinator/events/9"]}>
        <Routes>
          <Route path="/coordinator/events/:id" element={<CoordinatorEventDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CoordinatorEventDetail", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the full details of the event it was opened for", async () => {
    vi.mocked(getEvent).mockResolvedValue(event());

    renderPage();

    expect(await screen.findByRole("heading", { name: "Partner Summit" })).toBeInTheDocument();
    expect(getEvent).toHaveBeenCalledWith(9);
    expect(screen.getByText("Annual partner briefing")).toBeInTheDocument();
    expect(screen.getByText("Theatre")).toBeInTheDocument();
    expect(screen.getByText("Two projectors")).toBeInTheDocument();
    expect(screen.getByText("Wheelchair access")).toBeInTheDocument();
    expect(screen.getByText(/Acme Pte Ltd · raised by Ada Organiser/)).toBeInTheDocument();
  });

  it("lets the assigned coordinator approve a reviewable request", async () => {
    vi.mocked(getEvent).mockResolvedValue(event());
    vi.mocked(approveEvent).mockResolvedValue(
      event({
        status: "APPROVED",
        status_label: "Approved",
        approved_by_name: "Cora Coordinator",
        approved_at: "2026-09-25T02:00:00Z",
      }),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Approve request" }));

    expect(approveEvent).toHaveBeenCalledWith(9);
    expect(await screen.findByText(/Approved by Cora Coordinator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve request" })).not.toBeInTheDocument();
  });

  it("offers no Approve button to a coordinator who is not assigned", async () => {
    vi.mocked(getEvent).mockResolvedValue(event({ coordinator: 5 }));

    renderPage();

    expect(await screen.findByRole("heading", { name: "Partner Summit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve request" })).not.toBeInTheDocument();
  });

  it("SCRUM-49 AC1: the assigned coordinator sends a clarification request", async () => {
    vi.mocked(getEvent).mockResolvedValue(event());
    vi.mocked(requestClarification).mockResolvedValue(
      event({
        status: "UNDER_REVIEW",
        status_label: "Awaiting Clarification",
        clarifications: [
          {
            id: 1,
            message: "How many wheelchair users?",
            fields: ["accessibility_needs"],
            requested_by_name: "Cora Coordinator",
            requested_at: "2026-09-29T01:00:00Z",
            resolved_at: null,
            comments: [],
          },
        ],
      }),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Request clarification" }));
    await userEvent.type(
      screen.getByLabelText("What do you need from the client?"),
      "How many wheelchair users?",
    );
    await userEvent.click(screen.getByLabelText("Accessibility needs"));
    await userEvent.click(screen.getByRole("button", { name: "Send to client" }));

    expect(requestClarification).toHaveBeenCalledWith(9, "How many wheelchair users?", [
      "accessibility_needs",
    ]);
    expect(await screen.findByText("Clarification history")).toBeInTheDocument();
    expect(screen.getByText(/awaiting answer/)).toBeInTheDocument();
  });

  it("SCRUM-49 AC4: a clarification request without a message is not sent", async () => {
    vi.mocked(getEvent).mockResolvedValue(event());

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Request clarification" }));
    await userEvent.click(screen.getByRole("button", { name: "Send to client" }));

    expect(screen.getByText("Say what information is needed.")).toBeInTheDocument();
    expect(requestClarification).not.toHaveBeenCalled();
  });

  it("offers no clarification request once the event is not Submitted", async () => {
    vi.mocked(getEvent).mockResolvedValue(event({ status: "APPROVED", status_label: "Approved" }));

    renderPage();

    expect(await screen.findByRole("heading", { name: "Partner Summit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request clarification" })).not.toBeInTheDocument();
  });

  it("SCRUM-52 AC1: the assigned coordinator rejects with a reason", async () => {
    vi.mocked(getEvent).mockResolvedValue(event());
    vi.mocked(rejectEvent).mockResolvedValue(
      event({
        status: "REJECTED",
        status_label: "Rejected",
        rejection_reason: "Venue unavailable for 500 people.",
        rejected_at: "2026-09-29T03:00:00Z",
        rejected_by_name: "Cora Coordinator",
      }),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reject request" }));
    await userEvent.type(
      screen.getByLabelText("Why can ConnectSphere not support this request?"),
      "Venue unavailable for 500 people.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm rejection" }));

    expect(rejectEvent).toHaveBeenCalledWith(9, "Venue unavailable for 500 people.");
    expect(
      await screen.findByText("Reason: Venue unavailable for 500 people."),
    ).toBeInTheDocument();
    expect(screen.getByText(/by Cora Coordinator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve request" })).not.toBeInTheDocument();
  });

  it("SCRUM-52 AC2: a rejection without a reason is blocked", async () => {
    vi.mocked(getEvent).mockResolvedValue(event());

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reject request" }));
    await userEvent.type(
      screen.getByLabelText("Why can ConnectSphere not support this request?"),
      "   ",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm rejection" }));

    expect(screen.getByText("Enter a reason for the rejection.")).toBeInTheDocument();
    expect(rejectEvent).not.toHaveBeenCalled();
  });

  // SCRUM-61 - Update event information during planning. ---------------------

  it("SCRUM-61 AC1/AC5: the assigned coordinator edits details and only changes are sent", async () => {
    vi.mocked(getEvent).mockResolvedValue(event({ status: "PLANNING", is_editable: true }));
    vi.mocked(updateEvent).mockResolvedValue(
      event({
        status: "PLANNING",
        is_editable: true,
        name: "Partner Summit 2027",
        updated_by_name: "Cora Coordinator",
      }),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    const name = screen.getByLabelText("Event name");
    await userEvent.clear(name);
    await userEvent.type(name, "Partner Summit 2027");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(updateEvent).toHaveBeenCalledWith(9, { name: "Partner Summit 2027" });
    expect(await screen.findByRole("status")).toHaveTextContent("Changes saved.");
    expect(screen.getByText(/Last edited by Cora Coordinator/)).toBeInTheDocument();
  });

  it("SCRUM-61 AC2/AC3: no Edit details button when the coordinator may not edit", async () => {
    vi.mocked(getEvent).mockResolvedValue(event({ status: "CONFIRMED", is_editable: false }));

    renderPage();

    expect(await screen.findByRole("heading", { name: "Partner Summit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit details" })).not.toBeInTheDocument();
  });

  it("SCRUM-61: shows why the server refused an edit", async () => {
    vi.mocked(getEvent).mockResolvedValue(event({ status: "PLANNING", is_editable: true }));
    vi.mocked(updateEvent).mockRejectedValue(
      new ApiError(400, { expected_attendance: ["Expected attendance must be at least one person."] }, "Bad"),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    const attendance = screen.getByLabelText("Expected attendance");
    await userEvent.clear(attendance);
    await userEvent.type(attendance, "0");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("Expected attendance must be at least one person."),
    ).toBeInTheDocument();
  });

  // SCRUM-92 - Record offline clarification conversations. -------------------

  function awaiting(overrides: Partial<EventRequest> = {}) {
    return event({
      status: "UNDER_REVIEW",
      status_label: "Awaiting Clarification",
      is_editable: true,
      clarifications: [
        {
          id: 1,
          message: "How many wheelchair users?",
          fields: ["accessibility_needs"],
          requested_by_name: "Cora Coordinator",
          requested_at: "2026-09-29T01:00:00Z",
          resolved_at: null,
          comments: [
            {
              id: 5,
              body: "Client called: six wheelchair users.",
              author_name: "Ada Organiser",
              author_role: "Event Organiser",
              created_at: "2026-09-30T02:00:00Z",
            },
          ],
        },
      ],
      ...overrides,
    });
  }

  it("SCRUM-92 AC1: shows the notes and lets the coordinator add one", async () => {
    vi.mocked(getEvent).mockResolvedValue(awaiting());
    vi.mocked(addClarificationNote).mockResolvedValue(awaiting());

    renderPage();

    expect(await screen.findByText("Client called: six wheelchair users.")).toBeInTheDocument();
    expect(screen.getByText(/Ada Organiser \(Event Organiser\)/)).toBeInTheDocument();
    await userEvent.type(
      screen.getByLabelText("Add a note from your conversation"),
      "Confirmed ramp at entrance B.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));

    expect(addClarificationNote).toHaveBeenCalledWith(9, "Confirmed ramp at entrance B.");
  });

  it("SCRUM-92 AC4: the coordinator resumes review", async () => {
    vi.mocked(getEvent).mockResolvedValue(awaiting());
    vi.mocked(resumeReview).mockResolvedValue(event({ status: "SUBMITTED" }));

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Resume review" }));

    expect(resumeReview).toHaveBeenCalledWith(9);
    expect(await screen.findByRole("status")).toHaveTextContent("Review resumed.");
  });

  it("SCRUM-92: no resume or note box for a coordinator who is not assigned", async () => {
    vi.mocked(getEvent).mockResolvedValue(awaiting({ coordinator: 5, is_editable: false }));

    renderPage();

    expect(await screen.findByText("Client called: six wheelchair users.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume review" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Add a note from your conversation")).not.toBeInTheDocument();
  });
});

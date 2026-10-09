import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { approveEvent, getEvent, rejectEvent, requestClarification } from "../api/events";
import { fetchChangeRequests, fetchHistory } from "../api/planning";
import type { EventRequest } from "../types";
import { CoordinatorEventDetail } from "./CoordinatorEventDetail";

vi.mock("../api/events", () => ({
  getEvent: vi.fn(),
  approveEvent: vi.fn(),
  requestClarification: vi.fn(),
  rejectEvent: vi.fn(),
}));
vi.mock("../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/planning")>()),
  fetchHistory: vi.fn().mockResolvedValue([]),
  fetchChangeRequests: vi.fn().mockResolvedValue([]),
  fetchRegistrations: vi.fn().mockResolvedValue({
    capacity: 100,
    registered_count: 0,
    waitlist_count: 0,
    places_left: 100,
    registrations: [],
  }),
  fetchShortlist: vi.fn().mockResolvedValue([]),
  fetchBookings: vi.fn().mockResolvedValue([]),
  fetchEquipmentRequests: vi.fn().mockResolvedValue([]),
  fetchEquipmentAvailability: vi.fn().mockResolvedValue({
    event: 9,
    start: "",
    end: "",
    results: [],
  }),
  listEquipmentTypes: vi.fn().mockResolvedValue([]),
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
});

describe("SCRUM-61 / 11 / 74 / 78 / 60 planning panels on the event page", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows every planning panel to the assigned coordinator during planning", async () => {
    vi.mocked(getEvent).mockResolvedValue(event({ status: "PLANNING", status_label: "Planning" }));

    renderPage();

    expect(await screen.findByRole("button", { name: "Edit event details" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Find a venue" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Venue bookings" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Equipment requests" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Registrations" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm event" })).toBeInTheDocument();
    expect(await screen.findByText("No changes have been recorded yet.")).toBeInTheDocument();
    expect(fetchHistory).toHaveBeenCalledWith(9);
    expect(fetchChangeRequests).toHaveBeenCalledWith(9);
  });

  it("shows only history and change requests to a coordinator who is not assigned", async () => {
    vi.mocked(getEvent).mockResolvedValue(
      event({ status: "PLANNING", status_label: "Planning", coordinator: 5 }),
    );

    renderPage();

    expect(await screen.findByRole("region", { name: "Change history" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Change requests" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit event details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Find a venue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Registrations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel event" })).not.toBeInTheDocument();
  });

  it("offers no venue or equipment planning before the request is approved", async () => {
    vi.mocked(getEvent).mockResolvedValue(event());

    renderPage();

    expect(await screen.findByRole("button", { name: "Approve request" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Find a venue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Equipment requests" })).not.toBeInTheDocument();
  });
});

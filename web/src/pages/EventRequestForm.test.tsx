import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { addClarificationNote, createDraft, getEvent, submitEvent, updateDraft } from "../api/events";
import type { EventRequest } from "../types";
import { EventRequestForm } from "./EventRequestForm";
import { ApiError } from "../api/client";

vi.mock("../api/changeRequests", () => ({ listChangeRequests: async () => [], requestChange: async () => ({}) }));
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

function renderPage(path = "/organiser/requests/4") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/organiser/requests/new" element={<EventRequestForm />} />
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

it("SCRUM-86: preserves the original disrupted venue details for the organiser", async () => {
  vi.mocked(getEvent).mockResolvedValue({ ...awaitingClarification(), venue_disruptions: [{
    booking: 17, venue: "Original Hall", session: "Main programme", status: "Disrupted",
    starts_at: "2027-06-08T02:00:00Z", ends_at: "2027-06-08T04:00:00Z",
  }] });
  renderPage();
  expect(await screen.findByRole("region", { name: "Disrupted venue bookings" })).toHaveTextContent("Booking #17: Main programme, Original Hall");
  expect(screen.getByText(/Replacement arrangements require staff review/)).toBeInTheDocument();
});

describe("EventRequestForm draft persistence", () => {
  beforeEach(() => vi.clearAllMocks());

  function draft(): EventRequest {
    return {
      ...awaitingClarification(), status: "DRAFT", status_label: "Draft",
      status_description: "Not submitted", is_editable: true, submitted_at: null,
      clarifications: [], preferred_start: "2027-12-06T01:00:00Z",
      preferred_end: "2027-12-06T04:00:00Z",
      description: "Keep this description", equipment_notes: "One projector",
    };
  }

  it("SCRUM-8 AC2 saves an empty draft without submitting it", async () => {
    const saved = { ...draft(), name: "", purpose: "", preferred_start: null, preferred_end: null };
    vi.mocked(createDraft).mockResolvedValue(saved);
    vi.mocked(getEvent).mockResolvedValue(saved);
    renderPage("/organiser/requests/new");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(createDraft).toHaveBeenCalledWith(expect.objectContaining({
      name: "", purpose: "", preferred_start: null, expected_attendance: null,
    }));
    expect(submitEvent).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent("Draft saved.");
  });

  it("SCRUM-8 AC3 reopens the same instants and saves all unchanged fields", async () => {
    const saved = draft();
    vi.mocked(getEvent).mockResolvedValue(saved);
    vi.mocked(updateDraft).mockResolvedValue(saved);
    renderPage();
    const start = await screen.findByLabelText("Preferred start");
    await screen.findByDisplayValue("Partner Summit");
    // A datetime-local value, interpreted in the browser's timezone, must
    // represent the exact instant supplied by the API (not merely be non-null).
    expect(new Date((start as HTMLInputElement).value).toISOString()).toBe(new Date(saved.preferred_start!).toISOString());
    expect(new Date((screen.getByLabelText("Preferred end") as HTMLInputElement).value).toISOString()).toBe(new Date(saved.preferred_end!).toISOString());
    expect(screen.getByLabelText("Description")).toHaveValue("Keep this description");
    expect(screen.getByLabelText("Equipment and technical requirements")).toHaveValue("One projector");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(updateDraft).toHaveBeenCalledWith(4, expect.objectContaining({
      preferred_start: saved.preferred_start, preferred_end: saved.preferred_end,
      description: "Keep this description", equipment_notes: "One projector",
    }));
    expect(await screen.findByRole("status")).toHaveTextContent("Draft saved.");
  });

  it("SCRUM-1 AC1 refuses a foreign request instead of offering an editable blank form", async () => {
    vi.mocked(getEvent).mockRejectedValue(new ApiError(403, { detail: "Not your organisation." }, "Not your organisation."));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("do not have access");
    expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
    expect(createDraft).not.toHaveBeenCalled();
    expect(updateDraft).not.toHaveBeenCalled();
  });

  it("shows a failed draft save without reporting success", async () => {
    vi.mocked(getEvent).mockResolvedValue(draft());
    vi.mocked(updateDraft).mockRejectedValue(new Error("connection lost"));
    renderPage();
    await screen.findByDisplayValue("Partner Summit");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("status")).toHaveTextContent("We could not save this request");
    expect(screen.queryByText("Draft saved.")).not.toBeInTheDocument();
    expect(submitEvent).not.toHaveBeenCalled();
  });
});

describe("SCRUM-7/8/15 request validation regression gaps", () => {
  beforeEach(() => vi.clearAllMocks());

  it.each([
    ["detail-only", { detail: "This request changed while you were editing it." }, "This request changed while you were editing it."],
    ["field error", { purpose: ["Enter a purpose."] }, "Enter a purpose."],
    ["string field error", { name: "Enter an event name." }, "Enter an event name."],
  ])("shows a %s save refusal", async (_label, body, message) => {
    vi.mocked(getEvent).mockResolvedValue({ ...awaitingClarification(), status: "DRAFT", is_editable: true });
    vi.mocked(updateDraft).mockRejectedValue(new ApiError(400, body, String(message)));
    renderPage();
    await screen.findByDisplayValue("Partner Summit");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText(String(message))).toBeVisible();
    expect(screen.queryByText("Draft saved.")).not.toBeInTheDocument();
    expect(submitEvent).not.toHaveBeenCalled();
  });

  it("names incomplete submission fields and keeps the draft available for correction", async () => {
    const draft = { ...awaitingClarification(), status: "DRAFT" as const, is_editable: true };
    vi.mocked(getEvent).mockResolvedValue(draft);
    vi.mocked(updateDraft).mockResolvedValue(draft);
    vi.mocked(submitEvent).mockRejectedValue(new ApiError(400, {
      missing_fields: ["purpose", "preferred_start"], detail: "Complete the required information.",
      purpose: ["Enter a purpose."], preferred_start: ["Enter a start date."],
    }, "Complete the required information."));
    renderPage();
    await screen.findByDisplayValue("Partner Summit");
    await userEvent.click(screen.getByRole("button", { name: "Send to ConnectSphere" }));
    const summary = (await screen.findByText("This request cannot be sent yet. Still needed:")).closest('[role="alert"]');
    expect(summary).toHaveTextContent("Purpose");
    expect(summary).toHaveTextContent("Preferred start");
    expect(screen.getByRole("status")).toHaveTextContent("Complete the required information.");
    expect(screen.getByText("Enter a purpose.")).toBeVisible();
    expect(screen.getByLabelText("Event name")).toBeEnabled();
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
  });
});

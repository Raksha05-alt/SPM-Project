import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { approveEvent, getEvent } from "../api/events";
import type { EventRequest } from "../types";
import { CoordinatorEventDetail } from "./CoordinatorEventDetail";

vi.mock("../api/events", () => ({ getEvent: vi.fn(), approveEvent: vi.fn() }));
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
});

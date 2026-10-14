import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  decideSafetyCheck,
  getSafetyCheck,
  listSafetyChecks,
  type SafetyCheck,
  type SafetyFacts,
} from "../../api/safety";
import { SafetyCheckDetail } from "./SafetyCheckDetail";
import { SafetyQueue } from "./SafetyQueue";

vi.mock("../../api/safety", () => ({
  listSafetyChecks: vi.fn(),
  getSafetyCheck: vi.fn(),
  decideSafetyCheck: vi.fn(),
}));

function facts(overrides: Partial<SafetyFacts> = {}): SafetyFacts {
  return {
    event: 9,
    event_name: "Charity Run Briefing",
    expected_attendance: 120,
    required_layout: "Theatre",
    accessibility_needs: "Two wheelchair users",
    start: "2026-11-20T01:00:00Z",
    end: "2026-11-20T07:00:00Z",
    venues: [
      {
        booking: 1,
        venue: "Harbour Hall",
        session: "Main programme",
        location: "Level 1",
        capacity: 150,
        attendance: 120,
        layout: "Theatre",
        start: "2026-11-20T01:00:00Z",
        end: "2026-11-20T07:00:00Z",
        occupied_from: "2026-11-20T00:30:00Z",
        occupied_until: "2026-11-20T07:45:00Z",
        wheelchair_access: true,
        accessibility_notes: "Ramp at side entrance",
        safety_notes: "Four exits; assembly point at the plaza.",
      },
    ],
    equipment: [{ equipment: "Projector", quantity: 2, technical_requirements: "HDMI" }],
    concerns: ["Harbour Hall has no recorded fire warden."],
    ...overrides,
  };
}

function check(overrides: Partial<SafetyCheck> = {}): SafetyCheck {
  return {
    id: 4,
    event: 9,
    status: "PENDING",
    status_display: "Awaiting Safety Officer",
    requested_by_name: "Cora Coordinator",
    requested_at: "2026-10-10T01:00:00Z",
    request_note: "Outdoor queue expected",
    decided_by_name: null,
    decided_at: null,
    comment: "",
    superseded_at: null,
    superseded_reason: "",
    event_name: "Charity Run Briefing",
    event_status: "Planning",
    organisation_name: "Acme Pte Ltd",
    coordinator_name: "Cora Coordinator",
    facts: facts(),
    current_facts: facts(),
    ...overrides,
  };
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/safety/checks/4"]}>
        <Routes>
          <Route path="/safety/checks/:id" element={<SafetyCheckDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("Week 7 CR6 - the Safety Officer's queue", () => {
  it("AC2: lists checks awaiting a decision with the concerns to look at", async () => {
    vi.mocked(listSafetyChecks).mockResolvedValue([check()]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <SafetyQueue />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("link", { name: "Charity Run Briefing" })).toHaveAttribute(
      "href",
      "/safety/checks/4",
    );
    expect(screen.getByText("1 to look at")).toBeInTheDocument();
    expect(listSafetyChecks).toHaveBeenCalledWith(["PENDING"]);

    await userEvent.click(screen.getByRole("tab", { name: "Decided" }));
    expect(listSafetyChecks).toHaveBeenLastCalledWith(["APPROVED", "REJECTED", "CHANGES_REQUESTED"]);
  });
});

describe("Week 7 CR6 - deciding a safety check", () => {
  it("AC2: shows attendance, venue capacity, access, restrictions and equipment", async () => {
    vi.mocked(getSafetyCheck).mockResolvedValue(check());

    renderDetail();

    expect(await screen.findByText("From the coordinator: Outdoor queue expected")).toBeInTheDocument();
    expect(screen.getByText("Harbour Hall · Main programme")).toBeInTheDocument();
    expect(screen.getByText(/capacity 150 · 120 booked/)).toBeInTheDocument();
    expect(screen.getByText("Four exits; assembly point at the plaza.")).toBeInTheDocument();
    expect(screen.getByText(/Step-free access: yes/)).toBeInTheDocument();
    expect(screen.getByText("2 x Projector – HDMI")).toBeInTheDocument();
    expect(screen.getByText("Harbour Hall has no recorded fire warden.")).toBeInTheDocument();
  });

  it("AC3: approves without a comment", async () => {
    vi.mocked(getSafetyCheck).mockResolvedValue(check());
    vi.mocked(decideSafetyCheck).mockResolvedValue(
      check({ status: "APPROVED", status_display: "Approved", decided_by_name: "Sam Safety" }),
    );

    renderDetail();
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));

    expect(decideSafetyCheck).toHaveBeenCalledWith(4, "APPROVED", "");
    expect(await screen.findByText(/Approved by Sam Safety/)).toBeInTheDocument();
  });

  it.each([
    ["Reject safety arrangement", "REJECTED"],
    ["Request changes", "CHANGES_REQUESTED"],
  ])("AC3/AC4: %s needs a comment", async (button, decision) => {
    vi.mocked(getSafetyCheck).mockResolvedValue(check());
    vi.mocked(decideSafetyCheck).mockResolvedValue(check({ status: decision as never }));

    renderDetail();
    await userEvent.click(await screen.findByRole("button", { name: button }));
    expect(screen.getByRole("alert")).toHaveTextContent("Say what is unsafe or what must change.");
    expect(decideSafetyCheck).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText(/Comment/), "North exit blocked by the stage.");
    await userEvent.click(screen.getByRole("button", { name: button }));

    expect(decideSafetyCheck).toHaveBeenCalledWith(4, decision, "North exit blocked by the stage.");
  });

  it("shows a decided check read-only", async () => {
    vi.mocked(getSafetyCheck).mockResolvedValue(
      check({
        status: "SUPERSEDED",
        status_display: "Superseded by a later change",
        superseded_at: "2026-10-12T01:00:00Z",
        superseded_reason: "Quantity changed from 2 to 3.",
        current_facts: null,
      }),
    );

    renderDetail();

    expect(await screen.findByText("No longer applies: Quantity changed from 2 to 3.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });
});

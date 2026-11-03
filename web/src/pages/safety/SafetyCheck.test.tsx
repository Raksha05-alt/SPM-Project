import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { decideSafetyCheck, getSafetyCheck, listSafetyChecks } from "../../api/safety";
import type { SafetyCheckDetail, SafetyFacts } from "../../types";
import { SafetyCheckReview } from "./SafetyCheckReview";
import { SafetyQueue } from "./SafetyQueue";

vi.mock("../../api/safety", () => ({
  listSafetyChecks: vi.fn(),
  getSafetyCheck: vi.fn(),
  decideSafetyCheck: vi.fn(),
}));

const FACTS: SafetyFacts = {
  event: 9,
  event_name: "Partner Summit",
  organisation: "Acme Pte Ltd",
  expected_attendance: 120,
  starts_at: "2026-11-20T01:00:00Z",
  ends_at: "2026-11-20T07:00:00Z",
  required_layout: "Theatre",
  accessibility_needs: "Two wheelchair users.",
  venues: [
    {
      booking: 4,
      venue: "Harbour Hall",
      location: "Level 2, Marina Wing",
      capacity: 200,
      booked_attendance: 120,
      layout: "Theatre",
      starts_at: "2026-11-20T01:00:00Z",
      ends_at: "2026-11-20T07:00:00Z",
      wheelchair_access: true,
      accessibility_notes: "Step-free entrance.",
      required_facilities: [],
      wheelchair_access_required: true,
      booking_accessibility_notes: "",
      emergency_access: "Two fire exits to the stairwell.",
      known_restrictions: "",
    },
  ],
  equipment: [
    {
      equipment: "Projector",
      quantity: 2,
      reserved_quantity: 2,
      status: "Reserved",
      technical_requirements: "HDMI to both screens",
    },
  ],
  technical_approval: {
    approved_by: "Tariq Tech",
    approved_at: "2026-10-28T02:00:00Z",
    no_equipment_required: false,
    notes: "",
  },
  concerns: ["Harbour Hall has no known restrictions recorded."],
};

function check(overrides: Partial<SafetyCheckDetail> = {}): SafetyCheckDetail {
  return {
    id: 5,
    event: 9,
    event_name: "Partner Summit",
    event_status: "PLANNING",
    event_status_display: "Planning",
    event_start: "2026-11-20T01:00:00Z",
    organisation_name: "Acme Pte Ltd",
    coordinator_name: "Cora Coordinator",
    status: "PENDING",
    status_display: "Awaiting Safety Officer",
    requested_by_name: "Cora Coordinator",
    requested_at: "2026-10-29T02:00:00Z",
    request_note: "Stage moved forward.",
    decided_by_name: null,
    decided_at: null,
    comment: "",
    superseded_at: null,
    superseded_reason: "",
    is_stale: false,
    facts: FACTS,
    current_facts: FACTS,
    ...overrides,
  };
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/safety" element={<SafetyQueue />} />
          <Route path="/safety/checks/:id" element={<SafetyCheckReview />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SafetyQueue (SCRUM-90)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists checks awaiting a decision and links to each review", async () => {
    vi.mocked(listSafetyChecks).mockResolvedValue([check()]);
    renderAt("/safety");

    const link = await screen.findByRole("link", { name: "Partner Summit" });
    expect(link).toHaveAttribute("href", "/safety/checks/5");
    expect(screen.getByText("Awaiting Safety Officer")).toBeInTheDocument();
    expect(listSafetyChecks).toHaveBeenCalledWith(["PENDING"]);
  });

  it("can show every check, and says when there is nothing to decide", async () => {
    const user = userEvent.setup();
    vi.mocked(listSafetyChecks).mockResolvedValue([]);
    renderAt("/safety");

    expect(await screen.findByText("No safety checks are waiting for a decision.")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "All checks" }));
    expect(listSafetyChecks).toHaveBeenLastCalledWith([]);
  });
  it("allows a failed queue load to be retried", async () => {
    vi.mocked(listSafetyChecks).mockRejectedValueOnce(new Error("Network unavailable")).mockResolvedValue([]);
    renderAt("/safety");
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load the safety checks.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No safety checks are waiting for a decision.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

});

describe("SafetyCheckReview (SCRUM-90)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC2: shows attendance, venue capacity and layout, emergency access, restrictions, accessibility and equipment", async () => {
    vi.mocked(getSafetyCheck).mockResolvedValue(check());
    renderAt("/safety/checks/5");

    const venue = await screen.findByRole("article", { name: "Venue Harbour Hall" });
    expect(within(venue).getByText("200 / 120")).toBeInTheDocument();
    expect(within(venue).getByText("Theatre")).toBeInTheDocument();
    expect(within(venue).getByText("Two fire exits to the stairwell.")).toBeInTheDocument();
    // Missing information is named rather than left blank.
    expect(within(venue).getByText("Not recorded")).toBeInTheDocument();
    expect(screen.getByText("Two wheelchair users.")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("2 of 2 reserved")).toBeInTheDocument();
    expect(screen.getByText("HDMI to both screens")).toBeInTheDocument();
    expect(screen.getByText("Harbour Hall has no known restrictions recorded.")).toBeInTheDocument();
    expect(screen.getByText(/Stage moved forward/)).toBeInTheDocument();
  });

  it("AC3: approving needs no comment", async () => {
    const user = userEvent.setup();
    const approved = check({
      status: "APPROVED",
      status_display: "Approved",
      decided_by_name: "Sam Safety",
      decided_at: "2026-10-29T03:00:00Z",
      current_facts: null,
    });
    // First load is pending; the reload after the decision returns the approved check.
    vi.mocked(getSafetyCheck).mockResolvedValueOnce(check()).mockResolvedValue(approved);
    vi.mocked(decideSafetyCheck).mockResolvedValue(approved);
    renderAt("/safety/checks/5");

    await user.click(await screen.findByRole("radio", { name: /Approve/ }));
    await user.click(screen.getByRole("button", { name: "Record decision" }));

    expect(decideSafetyCheck).toHaveBeenCalledWith(5, "APPROVED", "");
    const decision = await screen.findByRole("region", { name: "Recorded decision" });
    expect(decision).toHaveTextContent("Approved by Sam Safety");
  });

  it.each([["Reject", "REJECTED"], ["Request changes", "CHANGES_REQUESTED"]] as const)(
    "AC3: %s needs a comment before anything is sent",
    async (label, value) => {
      const user = userEvent.setup();
      vi.mocked(getSafetyCheck).mockResolvedValue(check());
      vi.mocked(decideSafetyCheck).mockResolvedValue(check());
      renderAt("/safety/checks/5");

      await user.click(await screen.findByRole("radio", { name: new RegExp(label) }));
      await user.click(screen.getByRole("button", { name: "Record decision" }));
      expect(screen.getByRole("alert")).toHaveTextContent("Add a comment");
      expect(decideSafetyCheck).not.toHaveBeenCalled();

      await user.type(screen.getByLabelText(/Comment/), "Exit 2 is blocked.");
      await user.click(screen.getByRole("button", { name: "Record decision" }));
      expect(decideSafetyCheck).toHaveBeenCalledWith(5, value, "Exit 2 is blocked.");
    },
  );

  it("AC6: a stale check cannot be decided", async () => {
    vi.mocked(getSafetyCheck).mockResolvedValue(check({ is_stale: true }));
    renderAt("/safety/checks/5");

    expect(await screen.findByRole("alert")).toHaveTextContent("arrangements have changed");
    expect(screen.queryByRole("button", { name: "Record decision" })).not.toBeInTheDocument();
  });
  it("does not offer decisions when a check cannot be loaded", async () => {
    vi.mocked(getSafetyCheck).mockRejectedValue(new Error("Network unavailable"));
    renderAt("/safety/checks/5");
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load this safety check.");
    expect(screen.queryByRole("button", { name: "Record decision" })).not.toBeInTheDocument();
  });

  it("requires a selected decision and reports a server refusal", async () => {
    vi.mocked(getSafetyCheck).mockResolvedValue(check());
    vi.mocked(decideSafetyCheck).mockRejectedValue(new Error("The arrangements changed. Reload this check."));
    renderAt("/safety/checks/5");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Record decision" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose approve, request changes or reject.");
    expect(decideSafetyCheck).not.toHaveBeenCalled();
    await user.click(screen.getByRole("radio", { name: /^Approve/ }));
    await user.click(screen.getByRole("button", { name: "Record decision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The arrangements changed. Reload this check.");
    expect(screen.queryByRole("region", { name: "Recorded decision" })).not.toBeInTheDocument();
  });

  it("preserves superseded facts and the officer's decision for an empty equipment plan", async () => {
    vi.mocked(getSafetyCheck).mockResolvedValue(check({
      status: "SUPERSEDED", status_display: "Superseded by a later change", current_facts: null,
      decided_at: "2026-10-29T03:00:00Z", decided_by_name: "Sam Safety", comment: "Keep the exits clear.",
      superseded_at: "2026-10-30T03:00:00Z", superseded_reason: "Venue booking withdrawn.",
      facts: { ...FACTS, equipment: [], concerns: [], technical_approval: { ...FACTS.technical_approval!, no_equipment_required: true } },
    }));
    renderAt("/safety/checks/5");
    expect(await screen.findByText("Technical Support confirmed that no equipment is required.")).toBeInTheDocument();
    expect(screen.getByText(/Showing the arrangements as they were/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Recorded decision" })).toHaveTextContent("Decided by Sam Safety");
    expect(screen.getByText("Keep the exits clear.")).toBeInTheDocument();
    expect(screen.getByText(/Venue booking withdrawn./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record decision" })).not.toBeInTheDocument();
  });

});

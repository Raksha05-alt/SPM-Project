import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { getEventSafety, requestSafetyCheck } from "../../api/safety";
import type { EventSafetyState, SafetyCheck, EventStatus } from "../../types";
import { SafetyCheckPanel } from "./SafetyCheckPanel";

vi.mock("../../api/safety", () => ({ getEventSafety: vi.fn(), requestSafetyCheck: vi.fn() }));

const REJECTED: SafetyCheck = {
  id: 5,
  event: 9,
  event_name: "Partner Summit",
  event_status: "PLANNING",
  event_status_display: "Planning",
  event_start: null,
  organisation_name: "Acme Pte Ltd",
  coordinator_name: "Cora Coordinator",
  status: "REJECTED",
  status_display: "Rejected",
  requested_by_name: "Cora Coordinator",
  requested_at: "2026-10-29T02:00:00Z",
  request_note: "",
  decided_by_name: "Sam Safety",
  decided_at: "2026-10-29T03:00:00Z",
  comment: "Exit 2 is blocked by the stage.",
  superseded_at: null,
  superseded_reason: "",
  is_stale: false,
};

function state(overrides: Partial<EventSafetyState> = {}): EventSafetyState {
  return {
    checks: [],
    arrangement_gaps: [],
    confirmation_gaps: ["Operational safety check: no approved check."],
    can_request: true,
    ...overrides,
  };
}

function renderPanel(status: EventStatus = "PLANNING") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SafetyCheckPanel eventId={9} status={status} />
    </QueryClientProvider>,
  );
}

describe("SafetyCheckPanel (SCRUM-90)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: lists the missing arrangements and offers no request", async () => {
    vi.mocked(getEventSafety).mockResolvedValue(
      state({
        can_request: false,
        arrangement_gaps: ["Venue: no venue booking has been approved by Venue Staff."],
      }),
    );
    renderPanel();

    expect(
      await screen.findByText("Venue: no venue booking has been approved by Venue Staff."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Request/ })).not.toBeInTheDocument();
  });

  it("AC1/AC5: requests a check with a note and shows what blocks confirmation", async () => {
    const user = userEvent.setup();
    vi.mocked(getEventSafety).mockResolvedValue(state());
    vi.mocked(requestSafetyCheck).mockResolvedValue({} as never);
    renderPanel();

    expect(await screen.findByText("Operational safety check: no approved check.")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Note for the Safety Officer/), "Stage moved.");
    await user.click(screen.getByRole("button", { name: "Request safety check" }));

    expect(requestSafetyCheck).toHaveBeenCalledWith(9, "Stage moved.");
  });

  it("AC1: a refused request shows the gaps the API returned", async () => {
    const user = userEvent.setup();
    vi.mocked(getEventSafety).mockResolvedValue(state());
    vi.mocked(requestSafetyCheck).mockRejectedValue(
      new ApiError(
        409,
        {
          detail: "The venue and technical arrangements must all be in place before a safety check.",
          arrangement_gaps: ["Technical: the equipment plan has not been approved by Technical Support."],
        },
        "The venue and technical arrangements must all be in place before a safety check.",
      ),
    );
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Request safety check" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Technical: the equipment plan has not been approved by Technical Support.",
    );
  });

  it("AC4: shows the Safety Officer's comment and offers a new check", async () => {
    vi.mocked(getEventSafety).mockResolvedValue(state({ checks: [REJECTED] }));
    renderPanel();

    expect(await screen.findByText("Exit 2 is blocked by the stage.")).toBeInTheDocument();
    expect(screen.getByText(/Rejected by Sam Safety/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request a new safety check" })).toBeInTheDocument();
  });

  it("AC6: a superseded approval says why it no longer applies, not who superseded it", async () => {
    vi.mocked(getEventSafety).mockResolvedValue(
      state({
        checks: [
          {
            ...REJECTED,
            status: "SUPERSEDED",
            status_display: "Superseded by a later change",
            comment: "",
            superseded_at: "2026-10-30T01:00:00Z",
            superseded_reason: "Equipment request amended.",
          },
        ],
        arrangement_gaps: ["Technical: the equipment plan has not been approved by Technical Support."],
        can_request: false,
      }),
    );
    renderPanel();

    expect(await screen.findByText(/No longer applies: Equipment request amended./)).toBeInTheDocument();
    expect(screen.getByText(/Decided by Sam Safety/)).toBeInTheDocument();
    expect(screen.queryByText(/Superseded by a later change by/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Request/ })).not.toBeInTheDocument();
  });
  it("reports a failed load", async () => {
    vi.mocked(getEventSafety).mockRejectedValue(new Error("Connection lost"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load the safety check.");
  });

  it("keeps the earlier decision and reason after an arrangement change", async () => {
    vi.mocked(getEventSafety).mockResolvedValue(state({
      checks: [
        { ...REJECTED, id: 6, status: "PENDING", status_display: "Awaiting Safety Officer", decided_at: null, comment: "", is_stale: true },
        { ...REJECTED, superseded_reason: "Equipment request amended." },
      ], can_request: false,
    }));
    renderPanel();
    expect(await screen.findByText(/The arrangements changed after this check/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByText("Earlier checks (1)"));
    expect(screen.getByText(REJECTED.comment)).toBeVisible();
    expect(screen.getByText("Equipment request amended.")).toBeVisible();
    expect(screen.getByText(/Sam Safety/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Request/ })).not.toBeInTheDocument();
  });

  it("reports a network failure when requesting a check", async () => {
    vi.mocked(getEventSafety).mockResolvedValue(state());
    vi.mocked(requestSafetyCheck).mockRejectedValue(new Error("Connection lost. Try again."));
    renderPanel();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Request safety check" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost. Try again.");
  });

  it("does not show safety actions for a submitted event without checks", async () => {
    vi.mocked(getEventSafety).mockResolvedValue(state({can_request: false}));
    renderPanel("SUBMITTED");
    await vi.waitFor(() => expect(getEventSafety).toHaveBeenCalledWith(9));
    expect(screen.queryByRole("region", { name: "Operational safety check" })).not.toBeInTheDocument();
  });

});

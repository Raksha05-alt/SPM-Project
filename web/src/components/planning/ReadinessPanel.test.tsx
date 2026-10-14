import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { fetchReadiness, type Readiness } from "../../api/planning";
import { requestSafetyCheck } from "../../api/safety";
import { ReadinessPanel } from "./ReadinessPanel";

vi.mock("../../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/planning")>()),
  fetchReadiness: vi.fn(),
}));
vi.mock("../../api/safety", () => ({ requestSafetyCheck: vi.fn() }));

function readiness(overrides: Partial<Readiness> = {}): Readiness {
  return {
    status: "PLANNING",
    arrangements: [],
    safety_check: null,
    can_request_safety_check: true,
    can_confirm: false,
    missing: [
      { arrangement: "Safety", detail: "The operational safety check has not been requested." },
    ],
    ...overrides,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReadinessPanel eventId={9} />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("Week 7 CR6 - readiness and the safety check", () => {
  it("AC1: once arrangements are in place, sends the event for its safety check", async () => {
    vi.mocked(fetchReadiness).mockResolvedValue(readiness());
    vi.mocked(requestSafetyCheck).mockResolvedValue({} as never);

    renderPanel();
    await userEvent.type(await screen.findByLabelText(/Note for the Safety Officer/), "Outdoor queue");
    await userEvent.click(screen.getByRole("button", { name: "Request safety check" }));

    expect(requestSafetyCheck).toHaveBeenCalledWith(9, "Outdoor queue");
  });

  it("AC1: lists what is outstanding and offers no request until it is in place", async () => {
    vi.mocked(fetchReadiness).mockResolvedValue(
      readiness({
        can_request_safety_check: false,
        missing: [
          { arrangement: "Venue", detail: "Harbour Hall is only tentatively held. Confirm the hold." },
          { arrangement: "Safety", detail: "The operational safety check has not been requested." },
        ],
      }),
    );

    renderPanel();

    expect(await screen.findByText(/only tentatively held/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request safety check" })).not.toBeInTheDocument();
  });

  it("AC4: shows the Safety Officer's request for changes", async () => {
    vi.mocked(fetchReadiness).mockResolvedValue(
      readiness({
        safety_check: {
          id: 3,
          event: 9,
          status: "CHANGES_REQUESTED",
          status_display: "Changes requested",
          requested_by_name: "Cora Coordinator",
          requested_at: "2026-10-10T01:00:00Z",
          request_note: "",
          decided_by_name: "Sam Safety",
          decided_at: "2026-10-11T01:00:00Z",
          comment: "Move the registration desk away from the exit.",
          superseded_at: null,
          superseded_reason: "",
        },
      }),
    );

    renderPanel();

    expect(
      await screen.findByText("Safety Officer: Move the registration desk away from the exit."),
    ).toBeInTheDocument();
    expect(screen.getByText("Operational safety check: Changes requested")).toBeInTheDocument();
  });

  it("AC5: says when the event can be confirmed", async () => {
    vi.mocked(fetchReadiness).mockResolvedValue(
      readiness({ missing: [], can_confirm: true, can_request_safety_check: false }),
    );

    renderPanel();

    expect(await screen.findByText(/You can confirm the event/)).toBeInTheDocument();
  });

  it("shows a refused request with what is missing", async () => {
    vi.mocked(fetchReadiness).mockResolvedValue(readiness());
    vi.mocked(requestSafetyCheck).mockRejectedValue(
      new ApiError(
        409,
        { missing: [{ arrangement: "Venue", detail: "No venue booking has been approved." }] },
        "The venue and technical arrangements must be in place before the safety check.",
      ),
    );

    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Request safety check" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No venue booking has been approved.");
  });
});

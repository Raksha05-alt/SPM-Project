import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  confirmEvent,
  getConfirmedArrangements,
  getReadiness,
  type Readiness,
} from "../../api/confirmation";
import type { EventRequest } from "../../types";
import { ConfirmedArrangementsPanel } from "./ConfirmedArrangementsPanel";
import { ReadinessPanel } from "./ReadinessPanel";

vi.mock("../../api/confirmation", () => ({
  getReadiness: vi.fn(),
  confirmEvent: vi.fn(),
  getConfirmedArrangements: vi.fn(),
}));

const READY: Readiness = {
  event: 5,
  status: "PLANNING",
  items: [
    { area: "Venue", label: "Harbour Hall", ready: true, detail: "Approved by Venue Staff" },
    { area: "Technical", label: "Equipment plan", ready: true, detail: "Approved by Tariq Tech" },
    { area: "Safety", label: "Operational safety check", ready: true, detail: "Approved." },
  ],
  missing: [],
  unavailable: [],
  can_confirm: true,
  confirmed_by_name: null,
  confirmed_at: null,
};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

describe("ReadinessPanel (SCRUM-58)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1 - confirms an event whose arrangements are all approved", async () => {
    vi.mocked(getReadiness).mockResolvedValue(READY);
    vi.mocked(confirmEvent).mockResolvedValue({
      detail: '"Gala" is confirmed. The Event Organiser has been notified.',
      event: { id: 5, status: "CONFIRMED" } as EventRequest,
    });
    const user = userEvent.setup();
    wrap(<ReadinessPanel eventId={5} status="PLANNING" />);

    await user.click(await screen.findByRole("button", { name: "Confirm event" }));

    expect(confirmEvent).toHaveBeenCalledWith(5);
    expect(await screen.findByRole("status")).toHaveTextContent("Event Organiser has been notified");
  });

  it("AC2 - lists each missing item and disables Confirm", async () => {
    vi.mocked(getReadiness).mockResolvedValue({
      ...READY,
      can_confirm: false,
      missing: [
        "Venue: no venue booking has been approved by Venue Staff.",
        "Operational safety check: no approved check.",
      ],
      unavailable: ["Venue: Venue Staff rejected Harbour Hall: Closed for renovation."],
    });
    wrap(<ReadinessPanel eventId={5} status="PLANNING" />);

    expect(await screen.findByRole("button", { name: "Confirm event" })).toBeDisabled();
    expect(screen.getByText(/no venue booking has been approved/)).toBeInTheDocument();
    expect(screen.getByText("Operational safety check: no approved check.")).toBeInTheDocument();
    expect(screen.getByText(/Closed for renovation/)).toBeInTheDocument();
  });

  it("AC2 - shows the items the server says are missing when it refuses", async () => {
    vi.mocked(getReadiness).mockResolvedValue(READY);
    vi.mocked(confirmEvent).mockRejectedValue(
      new ApiError(
        409,
        {
          detail: "This event cannot be confirmed yet.",
          missing: ["Venue: Harbour Hall is out of service."],
        },
        "Conflict",
      ),
    );
    const user = userEvent.setup();
    wrap(<ReadinessPanel eventId={5} status="PLANNING" />);

    await user.click(await screen.findByRole("button", { name: "Confirm event" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This event cannot be confirmed yet.");
    expect(alert).toHaveTextContent("Venue: Harbour Hall is out of service.");
  });

  it("AC4 - a confirmed event shows who confirmed it, with no Confirm button", async () => {
    vi.mocked(getReadiness).mockResolvedValue({
      ...READY,
      status: "CONFIRMED",
      can_confirm: false,
      confirmed_by_name: "Cora Coordinator",
      confirmed_at: "2026-11-02T02:00:00Z",
    });
    wrap(<ReadinessPanel eventId={5} status="CONFIRMED" />);

    expect(await screen.findByText(/Confirmed by Cora Coordinator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm event" })).not.toBeInTheDocument();
  });

  it("is hidden before planning starts", () => {
    wrap(<ReadinessPanel eventId={5} status="SUBMITTED" />);

    expect(screen.queryByRole("region", { name: "Readiness" })).not.toBeInTheDocument();
    expect(getReadiness).not.toHaveBeenCalled();
  });
});

describe("ConfirmedArrangementsPanel (SCRUM-58 AC5)", () => {
  it("shows the organiser the confirmed venue, equipment and safety approval", async () => {
    vi.mocked(getConfirmedArrangements).mockResolvedValue({
      event: 5,
      status: "CONFIRMED",
      confirmed_by_name: "Cora Coordinator",
      confirmed_at: "2026-11-02T02:00:00Z",
      venues: [
        {
          venue: "Harbour Hall",
          location: "Level 2, Marina Wing",
          starts_at: "2026-12-02T01:00:00Z",
          ends_at: "2026-12-02T07:00:00Z",
          attendance: 120,
          layout: "Theatre",
        },
      ],
      equipment: [{ equipment: "Projector", quantity: 2 }],
      safety_approved_at: "2026-11-01T02:00:00Z",
    });
    wrap(<ConfirmedArrangementsPanel eventId={5} />);

    expect(await screen.findByText(/Harbour Hall, Level 2, Marina Wing/)).toBeInTheDocument();
    expect(screen.getByText(/120 people, Theatre/)).toBeInTheDocument();
    expect(screen.getByText("2 × Projector")).toBeInTheDocument();
    expect(screen.getByText(/Operational safety check approved/)).toBeInTheDocument();
    expect(screen.getByText(/Confirmed by Cora Coordinator/)).toBeInTheDocument();
  });
});

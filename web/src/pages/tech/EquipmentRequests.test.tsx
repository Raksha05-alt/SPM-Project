import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  listEquipmentRequests,
  markUnavailable,
  releaseReservation,
  reserveEquipment,
  reviewEquipmentRequest,
  type EquipmentRequest,
  type EquipmentReservation,
} from "../../api/equipment";
import { EquipmentRequests } from "./EquipmentRequests";

vi.mock("../../api/equipment", () => ({
  listEquipmentRequests: vi.fn(),
  reserveEquipment: vi.fn(),
  markUnavailable: vi.fn(),
  reviewEquipmentRequest: vi.fn(),
  releaseReservation: vi.fn(),
}));

function equipmentRequest(overrides: Partial<EquipmentRequest> = {}): EquipmentRequest {
  return {
    id: 1,
    event: 9,
    event_name: "Partner Summit",
    equipment_type: 3,
    equipment_name: "Projector",
    quantity: 2,
    technical_requirements: "HDMI input",
    status: "REQUESTED",
    status_display: "Requested",
    reserved_quantity: 0,
    requested_by_name: "Cora Coordinator",
    created_at: "2026-10-01T01:00:00Z",
    withdrawn_by_name: null,
    withdrawn_at: null,
    unavailable_reason: "",
    review_required: false,
    review_reason: "",
    reviewed_by_name: null,
    reviewed_at: null,
    review_outcome: "",
    reservations: [],
    changes: [],
    ...overrides,
  };
}

function reservation(overrides: Partial<EquipmentReservation> = {}): EquipmentReservation {
  return {
    id: 40,
    quantity: 2,
    start: "2026-10-20T01:00:00Z",
    end: "2026-10-20T07:00:00Z",
    reserved_by_name: "Tess Tech",
    reserved_at: "2026-10-02T01:00:00Z",
    released_at: null,
    released_by_name: null,
    release_reason: "",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <EquipmentRequests />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SCRUM-74 equipment requests for technical staff", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC3: lists every requested item per event with quantity and technical requirements", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([
      equipmentRequest(),
      equipmentRequest({
        id: 2,
        equipment_name: "Microphone",
        quantity: 4,
        technical_requirements: "Wireless",
      }),
      equipmentRequest({
        id: 3,
        event: 10,
        event_name: "Team Offsite",
        equipment_name: "Speaker",
        quantity: 1,
      }),
    ]);

    renderPage();

    const summit = await screen.findByRole("region", { name: "Partner Summit" });
    expect(within(summit).getByText("2 × Projector")).toBeInTheDocument();
    expect(within(summit).getByText("HDMI input")).toBeInTheDocument();
    expect(within(summit).getByText("4 × Microphone")).toBeInTheDocument();
    expect(within(summit).getByText("Wireless")).toBeInTheDocument();
    const offsite = screen.getByRole("region", { name: "Team Offsite" });
    expect(within(offsite).getByText("1 × Speaker")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Availability" })).toHaveAttribute(
      "href",
      "/equipment/availability",
    );
  });

  it("AC3: shows an error when the requests cannot be loaded", async () => {
    vi.mocked(listEquipmentRequests).mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not load the equipment requests.",
    );
  });
});

describe("SCRUM-16 reserve requested equipment", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: reserves the requested quantity", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([equipmentRequest()]);
    vi.mocked(reserveEquipment).mockResolvedValue(
      equipmentRequest({
        status: "RESERVED",
        status_display: "Reserved",
        reserved_quantity: 2,
        reservations: [reservation()],
      }),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reserve 2" }));

    expect(reserveEquipment).toHaveBeenCalledWith(1);
    expect(await screen.findByText("Reserved")).toBeInTheDocument();
    expect(screen.getByText("2 of 2 reserved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reserve 2" })).not.toBeInTheDocument();
  });

  it("AC3: shows the API refusal with the available quantity", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([equipmentRequest()]);
    vi.mocked(reserveEquipment).mockRejectedValue(
      new ApiError(
        409,
        {
          detail: "Only 1 x Projector available for this period; 2 requested.",
          available_quantity: 1,
        },
        "Only 1 x Projector available for this period; 2 requested.",
      ),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reserve 2" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Only 1 x Projector available for this period; 2 requested.");
    expect(alert).toHaveTextContent("Available quantity: 1.");
  });
});

describe("SCRUM-58 mark equipment unavailable", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC3: marks a request unavailable with a reason", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([equipmentRequest()]);
    vi.mocked(markUnavailable).mockResolvedValue(
      equipmentRequest({
        status: "UNAVAILABLE",
        status_display: "Unavailable",
        unavailable_reason: "All projectors are being repaired",
      }),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Mark unavailable" }));
    await userEvent.type(
      screen.getByLabelText("Why is this equipment unavailable?"),
      "All projectors are being repaired",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm unavailable" }));

    expect(markUnavailable).toHaveBeenCalledWith(1, "All projectors are being repaired");
    expect(
      await screen.findByText("Unavailable: All projectors are being repaired"),
    ).toBeInTheDocument();
  });

  it("AC3: a reason is required", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([equipmentRequest()]);

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Mark unavailable" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm unavailable" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter the reason the equipment is unavailable.",
    );
    expect(markUnavailable).not.toHaveBeenCalled();
  });

  it("AC3: shows the API refusal", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([equipmentRequest()]);
    vi.mocked(markUnavailable).mockRejectedValue(
      new ApiError(409, null, "A reserved request cannot be marked unavailable."),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Mark unavailable" }));
    await userEvent.type(screen.getByLabelText("Why is this equipment unavailable?"), "Broken");
    await userEvent.click(screen.getByRole("button", { name: "Confirm unavailable" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A reserved request cannot be marked unavailable.",
    );
  });
});

describe("SCRUM-77 release equipment reservations", () => {
  beforeEach(() => vi.clearAllMocks());

  const reserved = equipmentRequest({
    status: "RESERVED",
    status_display: "Reserved",
    reserved_quantity: 2,
    reservations: [reservation()],
  });

  it("AC2: releases an active reservation with a reason and shows who, when and why", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([reserved]);
    vi.mocked(releaseReservation).mockResolvedValue(
      equipmentRequest({
        reservations: [
          reservation({
            released_at: "2026-10-05T02:00:00Z",
            released_by_name: "Tess Tech",
            release_reason: "Needed for the board meeting",
          }),
        ],
      }),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Release reservation" }));
    await userEvent.type(
      screen.getByLabelText("Reason for releasing"),
      "Needed for the board meeting",
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm release" }));

    expect(releaseReservation).toHaveBeenCalledWith(40, "Needed for the board meeting");
    const when = new Date("2026-10-05T02:00:00Z").toLocaleString("en-SG");
    expect(
      await screen.findByText(new RegExp(`released by Tess Tech on ${when}`)),
    ).toHaveTextContent("Needed for the board meeting");
    expect(screen.queryByRole("button", { name: "Release reservation" })).not.toBeInTheDocument();
  });

  it("AC2: a reason is required", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([reserved]);

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Release reservation" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm release" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a reason for releasing this reservation.",
    );
    expect(releaseReservation).not.toHaveBeenCalled();
  });

  it("AC4: shows the refusal for an event that already took place", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([reserved]);
    vi.mocked(releaseReservation).mockRejectedValue(
      new ApiError(
        409,
        { detail: "The event has already taken place; its reservations are kept." },
        "The event has already taken place; its reservations are kept.",
      ),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Release reservation" }));
    await userEvent.type(screen.getByLabelText("Reason for releasing"), "Tidy up");
    await userEvent.click(screen.getByRole("button", { name: "Confirm release" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The event has already taken place; its reservations are kept.",
    );
  });
});

describe("SCRUM-80 review equipment after an event change", () => {
  beforeEach(() => vi.clearAllMocks());

  const flagged = equipmentRequest({
    status: "RESERVED",
    status_display: "Reserved",
    reserved_quantity: 2,
    reservations: [reservation()],
    review_required: true,
    review_reason: "The event moved to 22 Oct.",
  });

  it("AC1: shows the reason a request needs review", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([flagged]);
    renderPage();
    expect(
      await screen.findByText("Review needed: The event moved to 22 Oct."),
    ).toBeInTheDocument();
  });

  it("AC2: records that the change can be accommodated", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([flagged]);
    vi.mocked(reviewEquipmentRequest).mockResolvedValue({
      ...flagged,
      review_required: false,
      reviewed_by_name: "Tess Tech",
      review_outcome: "Reservation moved to the event's current period.",
    });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Accommodate" }));

    expect(reviewEquipmentRequest).toHaveBeenCalledWith(1, true, "");
    expect(
      await screen.findByText(/Review: Reservation moved to the event's current period\./),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accommodate" })).not.toBeInTheDocument();
  });

  it("AC2: shows the refusal when the new period has too little equipment", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([flagged]);
    vi.mocked(reviewEquipmentRequest).mockRejectedValue(
      new ApiError(
        409,
        { detail: "Only 1 x Projector available for the new period.", available_quantity: 1 },
        "Only 1 x Projector available for the new period.",
      ),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Accommodate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only 1 x Projector available for the new period. Available quantity: 1.",
    );
  });

  it("AC3: cannot accommodate requires a note and sends it", async () => {
    vi.mocked(listEquipmentRequests).mockResolvedValue([flagged]);
    vi.mocked(reviewEquipmentRequest).mockResolvedValue({
      ...flagged,
      review_required: false,
      review_outcome: "Could not accommodate the change: All units booked",
    });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Cannot accommodate" }));
    await userEvent.click(screen.getByRole("button", { name: "Record outcome" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Explain why the change cannot be accommodated.",
    );
    expect(reviewEquipmentRequest).not.toHaveBeenCalled();

    await userEvent.type(
      screen.getByLabelText("Why can the change not be accommodated?"),
      "All units booked",
    );
    await userEvent.click(screen.getByRole("button", { name: "Record outcome" }));

    expect(reviewEquipmentRequest).toHaveBeenCalledWith(1, false, "All units booked");
    expect(
      await screen.findByText(/Could not accommodate the change: All units booked/),
    ).toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { createVenue, listVenues } from "../../api/venues";
import type { Venue } from "../../api/venues";
import { VenueCatalogue } from "./VenueCatalogue";

vi.mock("../../api/venues", () => ({ listVenues: vi.fn(), createVenue: vi.fn() }));

function venue(overrides: Partial<Venue> = {}): Venue {
  return {
    id: 3,
    name: "Harbour Hall",
    location: "Level 2, Marina Tower",
    capacity: 200,
    facilities: ["Projector", "PA system"],
    layouts: ["THEATRE", "BANQUET"],
    layout_labels: ["Theatre", "Banquet"],
    wheelchair_access: true,
    accessibility_notes: "Lift at lobby",
    opens_at: "08:00:00",
    closes_at: "22:00:00",
    operating_days: [0, 1, 2, 3, 4],
    operating_hours: "08:00-22:00 (Mon, Tue, Wed, Thu, Fri)",
    is_active: true,
    operational_status: "In service",
    missing_information: [],
    updated_by_name: "Vera Venue",
    created_at: "2026-09-01T01:00:00Z",
    updated_at: "2026-09-01T01:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <VenueCatalogue />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SCRUM-9 venue catalogue", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: lists each venue's details, hours and operational status", async () => {
    vi.mocked(listVenues).mockResolvedValue([venue()]);
    renderPage();

    expect(await screen.findByRole("link", { name: "Harbour Hall" })).toHaveAttribute(
      "href",
      "/venues/3",
    );
    expect(screen.getByText("Level 2, Marina Tower")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("Theatre, Banquet")).toBeInTheDocument();
    expect(screen.getByText("Projector, PA system")).toBeInTheDocument();
    expect(screen.getByText("Wheelchair accessible · Lift at lobby")).toBeInTheDocument();
    expect(screen.getByText("08:00-22:00 (Mon, Tue, Wed, Thu, Fri)")).toBeInTheDocument();
    expect(screen.getByText("In service")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Booking requests" })).toBeInTheDocument();
  });

  it("AC3: shows the missing information of an incomplete entry", async () => {
    vi.mocked(listVenues).mockResolvedValue([
      venue({ missing_information: ["Facilities", "Operating hours"] }),
    ]);
    renderPage();

    expect(
      await screen.findByText("Missing information: Facilities, Operating hours"),
    ).toBeInTheDocument();
  });
});

describe("SCRUM-65 maintain venues", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: Venue Staff add a venue", async () => {
    vi.mocked(listVenues).mockResolvedValue([]);
    vi.mocked(createVenue).mockResolvedValue(venue({ id: 4, name: "Garden Room" }));
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Add venue" }));
    await userEvent.type(screen.getByLabelText("Name"), "Garden Room");
    await userEvent.type(screen.getByLabelText("Location"), "Level 1");
    await userEvent.type(screen.getByLabelText("Capacity"), "40");
    await userEvent.type(screen.getByLabelText("Facilities"), "Whiteboard, TV");
    await userEvent.click(screen.getByLabelText("Boardroom"));
    await userEvent.click(screen.getByRole("button", { name: "Save venue" }));

    expect(createVenue).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Garden Room",
        location: "Level 1",
        capacity: 40,
        facilities: ["Whiteboard", "TV"],
        layouts: ["BOARDROOM"],
      }),
    );
    expect(await screen.findByRole("button", { name: "Add venue" })).toBeInTheDocument();
  });

  it("AC3: shows the API's validation error next to the field", async () => {
    vi.mocked(listVenues).mockResolvedValue([]);
    vi.mocked(createVenue).mockRejectedValue(
      new ApiError(400, { capacity: ["Capacity must be at least one person."] }, "Bad request"),
    );
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Add venue" }));
    await userEvent.type(screen.getByLabelText("Capacity"), "0");
    await userEvent.click(screen.getByRole("button", { name: "Save venue" }));

    expect(await screen.findByText("Capacity must be at least one person.")).toBeInTheDocument();
  });

  it("AC4: shows the API's refusal message", async () => {
    vi.mocked(listVenues).mockResolvedValue([]);
    vi.mocked(createVenue).mockRejectedValue(
      new ApiError(403, { detail: "Only Venue Staff can change venue records." }, "Only Venue Staff can change venue records."),
    );
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Add venue" }));
    await userEvent.click(screen.getByRole("button", { name: "Save venue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only Venue Staff can change venue records.",
    );
  });

  it("AC5: offers no way to delete a venue", async () => {
    vi.mocked(listVenues).mockResolvedValue([venue()]);
    renderPage();

    await screen.findByRole("link", { name: "Harbour Hall" });
    expect(screen.queryByRole("button", { name: /delete|remove/i })).not.toBeInTheDocument();
  });
});

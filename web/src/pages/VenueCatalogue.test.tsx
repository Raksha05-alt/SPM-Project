import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { createVenue, listVenues, updateVenue } from "../api/venues";
import type { Venue } from "../types";
import { VenueCatalogue } from "./VenueCatalogue";

vi.mock("../api/venues", () => ({
  listVenues: vi.fn(),
  createVenue: vi.fn(),
  updateVenue: vi.fn(),
}));

const HALL: Venue = {
  id: 3,
  name: "Harbour Hall",
  location: "Level 2, Marina Wing",
  capacity: 200,
  facilities: ["Projector", "Stage"],
  layouts: ["THEATRE"],
  layout_labels: ["Theatre"],
  wheelchair_access: true,
  accessibility_notes: "Step-free entrance.",
  opens_at: "08:00:00",
  closes_at: "22:00:00",
  operating_days: [0, 1, 2, 3, 4],
  operating_hours: "08:00-22:00 (Mon, Tue, Wed, Thu, Fri)",
  setup_minutes: 60,
  turnaround_minutes: 45,
  emergency_access: "Three exits.",
  known_restrictions: "No open flames.",
  in_service: true,
  created_by_name: "Vera Venue",
  updated_by_name: "Vera Venue",
  created_at: "2026-10-01T02:00:00Z",
  updated_at: "2026-10-02T02:00:00Z",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VenueCatalogue />
    </QueryClientProvider>,
  );
}

describe("VenueCatalogue (SCRUM-65)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listVenues).mockResolvedValue([HALL]);
  });

  it("lists venues with capacity, setup and turnaround, status and last change", async () => {
    renderPage();

    const row = (await screen.findByText("Harbour Hall")).closest("tr")!;
    expect(within(row).getByText("200")).toBeInTheDocument();
    expect(within(row).getByText("60 / 45 min")).toBeInTheDocument();
    expect(within(row).getByText("In service")).toBeInTheDocument();
    expect(within(row).getByText(/by Vera Venue/)).toBeInTheDocument();
  });

  it("shows an empty state when there are no venues", async () => {
    vi.mocked(listVenues).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("No venues yet. Add the first one.")).toBeInTheDocument();
  });

  it("says so when the venues cannot be loaded", async () => {
    vi.mocked(listVenues).mockRejectedValue(new Error("down"));

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load the venues.");
  });

  it("AC1: records every venue detail, including setup, turnaround, emergency access and restrictions", async () => {
    const user = userEvent.setup();
    vi.mocked(createVenue).mockResolvedValue({ ...HALL, id: 9, name: "Skyline Room" });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Add venue" }));
    await user.type(screen.getByLabelText("Name"), "Skyline Room");
    await user.type(screen.getByLabelText("Location"), "Level 30");
    await user.clear(screen.getByLabelText("Maximum capacity"));
    await user.type(screen.getByLabelText("Maximum capacity"), "60");
    await user.type(screen.getByLabelText("Facilities"), "Whiteboard, Video conferencing");
    await user.clear(screen.getByLabelText("Setup time (minutes)"));
    await user.type(screen.getByLabelText("Setup time (minutes)"), "30");
    await user.clear(screen.getByLabelText("Turnaround time (minutes)"));
    await user.type(screen.getByLabelText("Turnaround time (minutes)"), "15");
    await user.type(screen.getByLabelText("Opens at"), "08:00");
    await user.type(screen.getByLabelText("Closes at"), "20:00");
    await user.click(screen.getByLabelText("Sat"));
    await user.click(screen.getByLabelText("Sun"));
    await user.click(screen.getByLabelText("Boardroom"));
    await user.selectOptions(screen.getByLabelText("Wheelchair access"), "true");
    await user.type(screen.getByLabelText("Accessibility information"), "Lift to level 30.");
    await user.type(screen.getByLabelText("Emergency access"), "Two stairwells.");
    await user.type(screen.getByLabelText("Known restrictions"), "Max 60 people.");
    await user.click(screen.getByRole("button", { name: "Save venue" }));

    expect(createVenue).toHaveBeenCalledWith({
      name: "Skyline Room",
      location: "Level 30",
      capacity: 60,
      facilities: ["Whiteboard", "Video conferencing"],
      layouts: ["BOARDROOM"],
      wheelchair_access: true,
      accessibility_notes: "Lift to level 30.",
      opens_at: "08:00",
      closes_at: "20:00",
      operating_days: [0, 1, 2, 3, 4],
      setup_minutes: 30,
      turnaround_minutes: 15,
      emergency_access: "Two stairwells.",
      known_restrictions: "Max 60 people.",
      in_service: true,
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Saved Skyline Room");
  });

  it("AC2: an update shows who saved it and when", async () => {
    const user = userEvent.setup();
    vi.mocked(updateVenue).mockResolvedValue({
      ...HALL,
      capacity: 220,
      updated_at: "2026-10-15T03:30:00Z",
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Edit Harbour Hall" }));
    expect(screen.getByLabelText("Opens at")).toHaveValue("08:00");
    await user.clear(screen.getByLabelText("Maximum capacity"));
    await user.type(screen.getByLabelText("Maximum capacity"), "220");
    await user.click(screen.getByRole("button", { name: "Save venue" }));

    expect(updateVenue).toHaveBeenCalledWith(3, expect.objectContaining({ capacity: 220 }));
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Saved Harbour Hall by Vera Venue at");
    expect(status).toHaveTextContent(new Date("2026-10-15T03:30:00Z").toLocaleString("en-SG"));
  });

  it("AC3: a zero capacity is blocked and the reason shown beside the field", async () => {
    const user = userEvent.setup();
    vi.mocked(updateVenue).mockRejectedValue(
      new ApiError(400, { capacity: ["Capacity must be at least one person."] }, "Bad request"),
    );
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Edit Harbour Hall" }));
    await user.clear(screen.getByLabelText("Maximum capacity"));
    await user.type(screen.getByLabelText("Maximum capacity"), "0");
    await user.click(screen.getByRole("button", { name: "Save venue" }));

    expect(await screen.findByText("Capacity must be at least one person.")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("AC4: a refusal from the server is explained", async () => {
    const user = userEvent.setup();
    vi.mocked(createVenue).mockRejectedValue(new ApiError(403, {}, "Forbidden"));
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Add venue" }));
    await user.type(screen.getByLabelText("Name"), "Annex");
    await user.click(screen.getByRole("button", { name: "Save venue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only Venue Staff can create or edit venues.",
    );
  });

  it("shows a general message for other save failures", async () => {
    const user = userEvent.setup();
    vi.mocked(createVenue).mockRejectedValue(new Error("network"));
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Add venue" }));
    await user.click(screen.getByRole("button", { name: "Save venue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not save the venue.");
  });

  it("AC5: warns before taking a venue out of service, then lists the disrupted bookings", async () => {
    const user = userEvent.setup();
    vi.mocked(updateVenue).mockResolvedValue({
      ...HALL,
      in_service: false,
      disrupted_bookings: [
        { id: 1, event: 4, event_name: "Leadership Offsite", start: "2026-12-01T01:00:00Z" },
      ],
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Edit Harbour Hall" }));
    await user.click(screen.getByLabelText("In service"));
    expect(screen.getByRole("note")).toHaveTextContent(
      "marks its future bookings Disrupted and informs their coordinators",
    );
    await user.click(screen.getByRole("button", { name: "Save venue" }));

    expect(updateVenue).toHaveBeenCalledWith(3, expect.objectContaining({ in_service: false }));
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("1 future booking is now Disrupted");
    expect(status).toHaveTextContent("Leadership Offsite");
  });

  it("cancel closes the form without saving", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Add venue" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("form", { name: "Venue details" })).not.toBeInTheDocument();
    expect(createVenue).not.toHaveBeenCalled();
  });
});

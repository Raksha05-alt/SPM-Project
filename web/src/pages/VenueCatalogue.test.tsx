import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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
  in_service: true,
  operational_status: "In service",
  missing_information: [],
  created_by_name: "Vera Venue",
  updated_by_name: "Vera Venue",
  created_at: "2026-10-01T02:00:00Z",
  updated_at: "2026-10-02T02:00:00Z",
};

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

describe("VenueCatalogue (SCRUM-65)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listVenues).mockResolvedValue([HALL]);
  });

  it("lists venues with capacity, status and last change", async () => {
    renderPage();

    const row = (await screen.findByText("Harbour Hall")).closest("tr")!;
    expect(within(row).getByText("200")).toBeInTheDocument();
    expect(within(row).getByText("In service")).toBeInTheDocument();
    expect(within(row).getByText(/by Vera Venue/)).toBeInTheDocument();
  });

  it("SCRUM-9 AC1: each venue links to its full details", async () => {
    renderPage();

    expect(await screen.findByRole("link", { name: "Harbour Hall" })).toHaveAttribute(
      "href",
      "/venues/3",
    );
  });

  it("SCRUM-9 AC3/AC4: flags venues with missing details and shows their status", async () => {
    vi.mocked(listVenues).mockResolvedValue([
      {
        ...HALL,
        operational_status: "Out of service",
        missing_information: ["Location", "Facilities"],
      },
    ]);

    renderPage();

    const row = (await screen.findByRole("link", { name: "Harbour Hall" })).closest("tr")!;
    expect(within(row).getByText("2 details not provided")).toBeInTheDocument();
    expect(within(row).getByText("Out of service")).toBeInTheDocument();
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

  it("AC1: records every venue detail", async () => {
    const user = userEvent.setup();
    vi.mocked(createVenue).mockResolvedValue({ ...HALL, id: 9, name: "Skyline Room" });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Add venue" }));
    await user.type(screen.getByLabelText("Name"), "Skyline Room");
    await user.type(screen.getByLabelText("Location"), "Level 30");
    await user.clear(screen.getByLabelText("Maximum capacity"));
    await user.type(screen.getByLabelText("Maximum capacity"), "60");
    await user.type(screen.getByLabelText("Facilities"), "Whiteboard, Video conferencing");
    await user.type(screen.getByLabelText("Opens at"), "08:00");
    await user.type(screen.getByLabelText("Closes at"), "20:00");
    await user.click(screen.getByLabelText("Sat"));
    await user.click(screen.getByLabelText("Sun"));
    await user.click(screen.getByLabelText("Boardroom"));
    await user.selectOptions(screen.getByLabelText("Wheelchair access"), "true");
    await user.type(screen.getByLabelText("Accessibility information"), "Lift to level 30.");
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

  it("cancel closes the form without saving", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Add venue" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("form", { name: "Venue details" })).not.toBeInTheDocument();
    expect(createVenue).not.toHaveBeenCalled();
  });
});

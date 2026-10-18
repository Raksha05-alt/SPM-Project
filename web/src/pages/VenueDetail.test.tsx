import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { getVenue } from "../api/venues";
import type { Venue } from "../types";
import { VenueDetail } from "./VenueDetail";

vi.mock("../api/venues", () => ({ getVenue: vi.fn() }));

const HALL: Venue = {
  id: 3,
  name: "Harbour Hall",
  location: "Level 2, Marina Wing",
  capacity: 200,
  facilities: ["Projector", "Stage"],
  layouts: ["THEATRE", "BANQUET"],
  layout_labels: ["Theatre", "Banquet"],
  wheelchair_access: true,
  accessibility_notes: "Step-free entrance",
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

function renderAt(path = "/venues/3") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/venues/:id" element={<VenueDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function detail(label: string) {
  const term = screen.getByText(label, { selector: "dt" });
  return within(term.parentElement as HTMLElement).getByRole("definition");
}

describe("VenueDetail (SCRUM-9)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC2: shows location, capacity, facilities, accessibility, layouts and hours", async () => {
    vi.mocked(getVenue).mockResolvedValue(HALL);

    renderAt();

    expect(await screen.findByRole("heading", { name: "Harbour Hall" })).toBeInTheDocument();
    expect(getVenue).toHaveBeenCalledWith(3);
    expect(detail("Location")).toHaveTextContent("Level 2, Marina Wing");
    expect(detail("Maximum capacity")).toHaveTextContent("200 people");
    expect(detail("Facilities")).toHaveTextContent("Projector, Stage");
    expect(detail("Accessibility information")).toHaveTextContent(
      "Wheelchair accessible. Step-free entrance",
    );
    expect(detail("Supported room layouts")).toHaveTextContent("Theatre, Banquet");
    expect(detail("Operating hours")).toHaveTextContent("08:00-22:00 (Mon, Tue, Wed, Thu, Fri)");
    expect(screen.queryByText("Not provided")).not.toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("AC3: names missing information instead of leaving it blank", async () => {
    vi.mocked(getVenue).mockResolvedValue({
      ...HALL,
      location: "",
      facilities: [],
      wheelchair_access: null,
      accessibility_notes: "",
      layout_labels: [],
      operating_hours: null,
      missing_information: [
        "Location",
        "Facilities",
        "Accessibility information",
        "Supported room layouts",
        "Operating hours",
      ],
    });

    renderAt();

    expect(await screen.findByRole("note")).toHaveTextContent(
      "Not provided yet: Location, Facilities, Accessibility information, Supported room layouts, Operating hours.",
    );
    for (const label of [
      "Location",
      "Facilities",
      "Accessibility information",
      "Supported room layouts",
      "Operating hours",
    ]) {
      expect(detail(label)).toHaveTextContent("Not provided");
    }
  });

  it("AC3: a venue recorded as not wheelchair accessible says so", async () => {
    vi.mocked(getVenue).mockResolvedValue({
      ...HALL,
      wheelchair_access: false,
      accessibility_notes: "",
    });

    renderAt();

    expect(await screen.findByText("Not wheelchair accessible")).toBeInTheDocument();
  });

  it.each([
    ["In service", "In service"],
    ["Out of service", "Out of service"],
  ] as const)("AC4: shows the operational status %s", async (status, text) => {
    vi.mocked(getVenue).mockResolvedValue({ ...HALL, operational_status: status });

    renderAt();

    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("explains a venue that does not exist", async () => {
    vi.mocked(getVenue).mockRejectedValue(new ApiError(404, {}, "Not found"));

    renderAt("/venues/99");

    expect(await screen.findByRole("alert")).toHaveTextContent("That venue does not exist.");
  });

  it("explains any other loading failure", async () => {
    vi.mocked(getVenue).mockRejectedValue(new Error("down"));

    renderAt();

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load this venue.");
  });

  it("links back to the catalogue", async () => {
    vi.mocked(getVenue).mockResolvedValue(HALL);

    renderAt();

    expect(await screen.findByRole("link", { name: "Back to venues" })).toHaveAttribute(
      "href",
      "/venues",
    );
  });
});

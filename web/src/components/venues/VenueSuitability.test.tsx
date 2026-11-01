import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getEventSuitability } from "../../api/suitability";
import type { EventSuitability } from "../../types";
import { VenueSuitability, parseFacilities } from "./VenueSuitability";

vi.mock("../../api/suitability", () => ({ getEventSuitability: vi.fn() }));

const RESULT: EventSuitability = {
  event: 9,
  requirements: {
    attendance: 120,
    layout: "THEATRE",
    layout_name: "Theatre",
    required_facilities: [],
    wheelchair_access_required: false,
    starts_at: "2026-11-02T01:00:00Z",
    ends_at: "2026-11-02T09:00:00Z",
  },
  not_checked: [
    "Whether the venue is free: bookings, blocks and operational status are checked separately (venue availability).",
    "Setup and turnaround buffers: added in Sprint 4 (SCRUM-85).",
  ],
  venues: [
    { venue: 1, venue_name: "Harbour Hall", suitable: true, reasons: [], in_service: true },
    {
      venue: 2,
      venue_name: "Skyline Room",
      suitable: false,
      in_service: true,
      reasons: [
        {
          requirement: "CAPACITY",
          message: "Expected attendance of 120 exceeds the venue's maximum capacity of 80.",
        },
        {
          requirement: "LAYOUT",
          message: "The venue does not support the required Theatre layout.",
        },
      ],
    },
    { venue: 3, venue_name: "Garden Pavilion", suitable: true, reasons: [], in_service: false },
  ],
};

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VenueSuitability eventId={9} />
    </QueryClientProvider>,
  );
}

describe("parseFacilities", () => {
  it("cleans and de-duplicates names, ignoring case", () => {
    expect(parseFacilities(" Hearing loop, , hearing LOOP,Stage")).toEqual([
      "Hearing loop",
      "Stage",
    ]);
  });

  it("returns nothing when no facility is required", () => {
    expect(parseFacilities("  ")).toEqual([]);
  });
});

describe("VenueSuitability (SCRUM-71)", () => {
  beforeEach(() => {
    vi.mocked(getEventSuitability).mockReset();
  });

  it("does not check until the coordinator asks", () => {
    renderSection();

    expect(getEventSuitability).not.toHaveBeenCalled();
  });

  it("AC1-AC2 shows each unsuitable venue with every reason it fails", async () => {
    vi.mocked(getEventSuitability).mockResolvedValue(RESULT);
    renderSection();

    await userEvent.click(screen.getByRole("button", { name: "Check venues" }));

    const skyline = await screen.findByRole("listitem", { name: "Skyline Room" });
    expect(within(skyline).getByText("Not suitable")).toBeInTheDocument();
    expect(
      within(skyline).getByText(
        "Expected attendance of 120 exceeds the venue's maximum capacity of 80.",
      ),
    ).toBeInTheDocument();
    expect(
      within(skyline).getByText("The venue does not support the required Theatre layout."),
    ).toBeInTheDocument();
  });

  it("AC5 shows a suitable venue with no warnings", async () => {
    vi.mocked(getEventSuitability).mockResolvedValue(RESULT);
    renderSection();

    await userEvent.click(screen.getByRole("button", { name: "Check venues" }));

    const harbour = await screen.findByRole("listitem", { name: "Harbour Hall" });
    expect(within(harbour).getByText("Suitable")).toBeInTheDocument();
    expect(within(harbour).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("states what was checked and what was not, so suitable is not read as free", async () => {
    vi.mocked(getEventSuitability).mockResolvedValue(RESULT);
    renderSection();

    await userEvent.click(screen.getByRole("button", { name: "Check venues" }));

    expect(
      await screen.findByText("Checked against: 120 attendees · Theatre layout"),
    ).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Whether the venue is free");
    const garden = screen.getByRole("listitem", { name: "Garden Pavilion" });
    expect(within(garden).getByText("Out of service")).toBeInTheDocument();
    expect(within(garden).getByText("Suitable")).toBeInTheDocument();
  });

  it("AC2 sends wheelchair access and the required facilities with the check", async () => {
    vi.mocked(getEventSuitability).mockResolvedValue({
      ...RESULT,
      requirements: {
        ...RESULT.requirements,
        wheelchair_access_required: true,
        required_facilities: ["Hearing loop"],
      },
      venues: [],
    });
    renderSection();

    await userEvent.click(screen.getByRole("checkbox", { name: "Step-free wheelchair access" }));
    await userEvent.type(screen.getByLabelText(/Required facilities/), "Hearing loop, hearing loop");
    await userEvent.click(screen.getByRole("button", { name: "Check venues" }));

    expect(getEventSuitability).toHaveBeenCalledWith(9, ["Hearing loop"], true);
    expect(await screen.findByText("No venues have been recorded yet.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Checked against: 120 attendees · Theatre layout · wheelchair access · Hearing loop",
      ),
    ).toBeInTheDocument();
  });

  it("says so when the check fails rather than showing a blank list", async () => {
    vi.mocked(getEventSuitability).mockRejectedValue(new Error("boom"));
    renderSection();

    await userEvent.click(screen.getByRole("button", { name: "Check venues" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not check the venues.");
  });
});

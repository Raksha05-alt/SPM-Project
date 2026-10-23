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
  required_facilities: [],
  venues: [
    { venue: 1, venue_name: "Harbour Hall", suitable: true, reasons: [] },
    {
      venue: 2,
      venue_name: "Skyline Room",
      suitable: false,
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
  it("cleans, de-duplicates and puts wheelchair access first", () => {
    expect(parseFacilities(" Hearing loop, , hearing LOOP,Braille", true)).toEqual([
      "Wheelchair access",
      "Hearing loop",
      "Braille",
    ]);
  });

  it("returns nothing when no facility is required", () => {
    expect(parseFacilities("  ", false)).toEqual([]);
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

  it("AC2 sends the required accessibility facilities with the check", async () => {
    vi.mocked(getEventSuitability).mockResolvedValue({ ...RESULT, venues: [] });
    renderSection();

    await userEvent.click(screen.getByRole("checkbox", { name: "Step-free wheelchair access" }));
    await userEvent.type(screen.getByLabelText(/Other facilities/), "Hearing loop");
    await userEvent.click(screen.getByRole("button", { name: "Check venues" }));

    expect(getEventSuitability).toHaveBeenCalledWith(9, ["Wheelchair access", "Hearing loop"]);
    expect(await screen.findByText("No venues have been recorded yet.")).toBeInTheDocument();
  });

  it("says so when the check fails rather than showing a blank list", async () => {
    vi.mocked(getEventSuitability).mockRejectedValue(new Error("boom"));
    renderSection();

    await userEvent.click(screen.getByRole("button", { name: "Check venues" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not check the venues.");
  });
});

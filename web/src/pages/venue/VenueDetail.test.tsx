import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  createBlock,
  deleteBlock,
  getAvailability,
  getVenue,
  listBlocks,
  updateBlock,
  updateVenue,
} from "../../api/venues";
import type { Venue, VenueBlock } from "../../api/venues";
import { VenueDetail } from "./VenueDetail";

vi.mock("../../api/venues", () => ({
  getVenue: vi.fn(),
  updateVenue: vi.fn(),
  listBlocks: vi.fn(),
  createBlock: vi.fn(),
  updateBlock: vi.fn(),
  deleteBlock: vi.fn(),
  getAvailability: vi.fn(),
}));

function venue(overrides: Partial<Venue> = {}): Venue {
  return {
    id: 3,
    name: "Harbour Hall",
    location: "Level 2, Marina Tower",
    capacity: 200,
    facilities: ["Projector"],
    layouts: ["THEATRE", "BANQUET"],
    layout_labels: ["Theatre", "Banquet"],
    wheelchair_access: true,
    accessibility_notes: "",
    opens_at: "08:00:00",
    closes_at: "22:00:00",
    operating_days: [0, 1, 2, 3, 4],
    operating_hours: "08:00-22:00 (Mon, Tue, Wed, Thu, Fri)",
    is_active: true,
    operational_status: "In service",
    missing_information: [],
    updated_by_name: null,
    created_at: "2026-09-01T01:00:00Z",
    updated_at: "2026-09-01T01:00:00Z",
    ...overrides,
  };
}

function block(overrides: Partial<VenueBlock> = {}): VenueBlock {
  return {
    id: 11,
    venue: 3,
    venue_name: "Harbour Hall",
    start: "2026-10-12T01:00:00Z",
    end: "2026-10-12T05:00:00Z",
    reason: "Carpet replacement",
    created_by_name: "Vera Venue",
    created_at: "2026-10-01T01:00:00Z",
    updated_by_name: "Vera Venue",
    updated_at: "2026-10-01T01:00:00Z",
    ...overrides,
  };
}

const fmt = (value: string) => new Date(value).toLocaleString("en-SG");

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/venues/3"]}>
        <Routes>
          <Route path="/venues/:id" element={<VenueDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getVenue).mockResolvedValue(venue());
  vi.mocked(listBlocks).mockResolvedValue([]);
  vi.mocked(getAvailability).mockResolvedValue({
    venue: 3,
    venue_name: "Harbour Hall",
    start: "2026-10-12T00:00:00Z",
    end: "2026-10-19T00:00:00Z",
    segments: [],
  });
});

describe("SCRUM-65 maintain venues", () => {
  it("AC2: Venue Staff edit a venue's details", async () => {
    vi.mocked(updateVenue).mockResolvedValue(venue({ capacity: 250 }));
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Edit venue" }));
    const capacity = screen.getByLabelText("Capacity");
    await userEvent.clear(capacity);
    await userEvent.type(capacity, "250");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(updateVenue).toHaveBeenCalledWith(
      3,
      expect.objectContaining({ capacity: 250, opens_at: "08:00", closes_at: "22:00" }),
      false,
    );
    expect(await screen.findByText("250")).toBeInTheDocument();
  });

  it("AC3: shows each field's validation error from the API", async () => {
    vi.mocked(updateVenue).mockRejectedValue(
      new ApiError(
        400,
        { name: ["venue with this name already exists."], closes_at: "Closing time must be after opening." },
        "Bad request",
      ),
    );
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Edit venue" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("venue with this name already exists.")).toBeInTheDocument();
    expect(screen.getByText("Closing time must be after opening.")).toBeInTheDocument();
  });
});

describe("SCRUM-5 layouts and facilities", () => {
  it("AC4: confirms before removing a layout that confirmed bookings use", async () => {
    vi.mocked(updateVenue)
      .mockRejectedValueOnce(
        new ApiError(
          409,
          {
            detail: "Confirmed bookings use a layout you are removing.",
            affected_bookings: [
              {
                id: 5,
                event: 9,
                event_name: "Partner Summit",
                layout: "Banquet",
                start: "2026-10-20T01:00:00Z",
                end: "2026-10-20T07:00:00Z",
              },
            ],
          },
          "Confirmed bookings use a layout you are removing.",
        ),
      )
      .mockResolvedValueOnce(venue({ layouts: ["THEATRE"], layout_labels: ["Theatre"] }));
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Edit venue" }));
    await userEvent.click(screen.getByLabelText("Banquet"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Confirmed bookings use a layout you are removing.",
    );
    expect(screen.getByText(/Partner Summit · Banquet/)).toBeInTheDocument();
    expect(updateVenue).toHaveBeenLastCalledWith(
      3,
      expect.objectContaining({ layouts: ["THEATRE"] }),
      false,
    );

    await userEvent.click(screen.getByRole("button", { name: "Remove layout anyway" }));

    expect(updateVenue).toHaveBeenLastCalledWith(
      3,
      expect.objectContaining({ layouts: ["THEATRE"] }),
      true,
    );
    expect(await screen.findByRole("button", { name: "Edit venue" })).toBeInTheDocument();
  });
});

describe("SCRUM-13 block a venue", () => {
  it("AC1: adds a block with start, end and reason", async () => {
    vi.mocked(createBlock).mockResolvedValue(block());
    renderPage();

    const section = await screen.findByRole("region", { name: "Blocks" });
    fireEvent.change(within(section).getByLabelText("Block start"), {
      target: { value: "2026-10-12T09:00" },
    });
    fireEvent.change(within(section).getByLabelText("Block end"), {
      target: { value: "2026-10-12T13:00" },
    });
    await userEvent.type(within(section).getByLabelText("Reason"), "Carpet replacement");
    await userEvent.click(within(section).getByRole("button", { name: "Add block" }));

    expect(createBlock).toHaveBeenCalledWith(3, {
      start: new Date("2026-10-12T09:00").toISOString(),
      end: new Date("2026-10-12T13:00").toISOString(),
      reason: "Carpet replacement",
    });
  });

  it("AC3: a block without a reason is not sent", async () => {
    renderPage();

    const section = await screen.findByRole("region", { name: "Blocks" });
    fireEvent.change(within(section).getByLabelText("Block start"), {
      target: { value: "2026-10-12T09:00" },
    });
    fireEvent.change(within(section).getByLabelText("Block end"), {
      target: { value: "2026-10-12T13:00" },
    });
    await userEvent.click(within(section).getByRole("button", { name: "Add block" }));

    expect(screen.getByText("Say why the venue is unavailable.")).toBeInTheDocument();
    expect(createBlock).not.toHaveBeenCalled();
  });

  it("AC3: shows the API's refusal of a block", async () => {
    vi.mocked(createBlock).mockRejectedValue(
      new ApiError(400, { end: ["The block must end after it starts."] }, "Bad request"),
    );
    renderPage();

    const section = await screen.findByRole("region", { name: "Blocks" });
    fireEvent.change(within(section).getByLabelText("Block start"), {
      target: { value: "2026-10-12T13:00" },
    });
    fireEvent.change(within(section).getByLabelText("Block end"), {
      target: { value: "2026-10-12T09:00" },
    });
    await userEvent.type(within(section).getByLabelText("Reason"), "Works");
    await userEvent.click(within(section).getByRole("button", { name: "Add block" }));

    expect(await screen.findByText("The block must end after it starts.")).toBeInTheDocument();
  });

  it("AC5: lists active blocks", async () => {
    vi.mocked(listBlocks).mockResolvedValue([block()]);
    renderPage();

    expect(
      await screen.findByText(
        `${fmt("2026-10-12T01:00:00Z")} – ${fmt("2026-10-12T05:00:00Z")} · Carpet replacement`,
      ),
    ).toBeInTheDocument();
  });

  it("AC6: edits a block", async () => {
    vi.mocked(listBlocks).mockResolvedValue([block()]);
    vi.mocked(updateBlock).mockResolvedValue(block({ reason: "Floor polishing" }));
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const reason = screen.getAllByLabelText("Reason")[0];
    await userEvent.clear(reason);
    await userEvent.type(reason, "Floor polishing");
    await userEvent.click(screen.getByRole("button", { name: "Save block" }));

    expect(updateBlock).toHaveBeenCalledWith(11, {
      start: "2026-10-12T01:00:00.000Z",
      end: "2026-10-12T05:00:00.000Z",
      reason: "Floor polishing",
    });
  });

  it("AC6: removes a block", async () => {
    vi.mocked(listBlocks).mockResolvedValue([block()]);
    vi.mocked(deleteBlock).mockResolvedValue(undefined);
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));

    expect(deleteBlock).toHaveBeenCalledWith(11);
  });
});

describe("SCRUM-17 venue availability", () => {
  it("AC1: shows the next 7 days by default with each segment's status and event", async () => {
    vi.mocked(getAvailability).mockResolvedValue({
      venue: 3,
      venue_name: "Harbour Hall",
      start: "2026-10-12T00:00:00Z",
      end: "2026-10-19T00:00:00Z",
      segments: [
        {
          start: "2026-10-12T00:00:00Z",
          end: "2026-10-12T02:00:00Z",
          status: "AVAILABLE",
          label: "Available",
          detail: "",
          event: null,
          event_name: null,
        },
        {
          start: "2026-10-12T02:00:00Z",
          end: "2026-10-12T06:00:00Z",
          status: "CONFIRMED",
          label: "Confirmed booking",
          detail: "Confirmed booking",
          event: 9,
          event_name: "Partner Summit",
        },
      ],
    });
    renderPage();

    expect(await screen.findByText("Partner Summit")).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
    expect(screen.getAllByText("Confirmed booking")).toHaveLength(1);
    const [, start, end] = vi.mocked(getAvailability).mock.calls[0];
    expect(new Date(end).getTime() - new Date(start).getTime()).toBe(7 * 24 * 60 * 60 * 1000);
  });

  it("AC2: loads a chosen period and shows the API's refusal", async () => {
    renderPage();
    await screen.findByRole("region", { name: "Availability" });
    vi.mocked(getAvailability).mockRejectedValue(
      new ApiError(400, { detail: "Choose a period of 31 days or less." }, "Choose a period of 31 days or less."),
    );

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-01T00:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-12-15T00:00" } });
    await userEvent.click(screen.getByRole("button", { name: "Show availability" }));

    expect(getAvailability).toHaveBeenLastCalledWith(
      3,
      new Date("2026-11-01T00:00").toISOString(),
      new Date("2026-12-15T00:00").toISOString(),
    );
    expect(await screen.findByText("Choose a period of 31 days or less.")).toBeInTheDocument();
  });
});

import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { getEvent } from "../api/events";
import {
  addVenueToShortlist,
  getVenueShortlist,
  removeVenueFromShortlist,
  searchVenues,
  type ShortlistEntry,
  type VenueMatch,
} from "../api/venueDiscovery";
import type { EventRequest } from "../types";
import { VenueDiscoveryPage } from "./VenueDiscovery";

vi.mock("../api/venueDiscovery", () => ({
  searchVenues: vi.fn(),
  getVenueShortlist: vi.fn(),
  addVenueToShortlist: vi.fn(),
  removeVenueFromShortlist: vi.fn(),
}));
vi.mock("../api/events", () => ({ getEvent: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { id: 2 } }) }));

const EVENT: EventRequest = {
  id: 9,
  name: "Partner Summit",
  purpose: "Planning",
  description: "",
  preferred_start: "2027-03-01T01:00:00Z",
  preferred_end: "2027-03-01T09:00:00Z",
  expected_attendance: 60,
  required_layout: "THEATRE",
  accessibility_needs: "",
  equipment_notes: "",
  registration_required: false,
  status: "PLANNING",
  status_label: "Planning",
  status_description: "Planning",
  status_changed_at: null,
  submitted_at: null,
  organisation_name: "Acme",
  created_by_name: "Ada",
  coordinator: 2,
  coordinator_name: "Cora",
  coordinator_email: "cora@cs.example",
  assignment_requires_attention: false,
  rejection_reason: "",
  rejected_at: null,
  clarifications: [],
  missing_mandatory_fields: [],
  is_editable: false,
  created_at: "2026-10-18T01:00:00Z",
  updated_at: "2026-10-18T01:00:00Z",
};
const MATCH: VenueMatch = {
  venue: {
    id: 3,
    name: "Harbour Hall",
    location: "Level 2",
    capacity: 60,
    facilities: ["Projector"],
    layouts: ["THEATRE"],
    layout_labels: ["Theatre"],
    wheelchair_access: true,
    accessibility_notes: "",
    opens_at: "08:00",
    closes_at: "22:00",
    operating_days: [0, 1, 2, 3, 4],
    operating_hours: "08:00-22:00",
    in_service: true,
    operational_status: "In service",
    missing_information: [],
    created_by_name: "Vera",
    updated_by_name: "Vera",
    created_at: "2026-10-18T01:00:00Z",
    updated_at: "2026-10-18T01:00:00Z",
  },
  criteria: [
    {
      key: "attendance",
      label: "Capacity",
      result: "MATCH",
      message: "Required: 60; recorded capacity: 60.",
    },
    {
      key: "approved_bookings",
      label: "Approved bookings",
      result: "MATCH",
      message: "No approved booking overlaps this period.",
    },
  ],
  matches_recorded_requirements: true,
  availability_status: "AVAILABLE",
};
const ENTRY: ShortlistEntry = {
  id: 4,
  created_at: "2026-10-18T01:00:00Z",
  search_criteria: { attendance: 60 },
  match: MATCH,
};
let entries: ShortlistEntry[];

function renderPage(path = "/coordinator/events/9/venues") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/coordinator/venues" element={<VenueDiscoveryPage />} />
          <Route path="/coordinator/events/:id/venues" element={<VenueDiscoveryPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SCRUM-64/68 venue discovery", () => {
  afterEach(() => focusManager.setFocused(undefined));
  beforeEach(() => {
    vi.clearAllMocks();
    entries = [];
    vi.mocked(getEvent).mockResolvedValue(EVENT);
    vi.mocked(searchVenues).mockImplementation(async (criteria) => ({
      results: [MATCH],
      criteria,
      availability_integrated: true,
      booking_occupancy_integrated: true,
      holds_integrated: false,
      date_blocks_integrated: true,
      limitation: "Availability reflects approved bookings, recorded blocks and operating hours. Search results do not reserve a venue.",
    }));
    vi.mocked(getVenueShortlist).mockImplementation(async () => ({
      event_id: 9,
      can_edit: true,
      entries: [...entries],
      availability_integrated: true,
      booking_occupancy_integrated: true,
      holds_integrated: false,
      date_blocks_integrated: true,
      limitation: "Verify with Venue Staff.",
    }));
    vi.mocked(addVenueToShortlist).mockImplementation(async () => {
      entries = [ENTRY];
      return ENTRY;
    });
    vi.mocked(removeVenueFromShortlist).mockImplementation(async () => {
      entries = [];
    });
  });

  it("SCRUM-64 AC1: prefills event filters and sends combined submitted values", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Harbour Hall" });
    expect(screen.getByLabelText("Expected attendance")).toHaveValue(60);
    expect(screen.getByLabelText("Required room layout")).toHaveValue("THEATRE");
    await user.type(screen.getByLabelText("Required facilities"), "Projector, Hearing loop");
    await user.click(screen.getByRole("button", { name: "Search venues" }));
    await waitFor(() =>
      expect(searchVenues).toHaveBeenLastCalledWith({
        start: "2027-03-01T01:00:00.000Z",
        end: "2027-03-01T09:00:00.000Z",
        attendance: 60,
        layout: "THEATRE",
        facilities: ["Projector", "Hearing loop"],
      }),
    );
    expect(screen.getByRole("note")).toHaveTextContent("Search results do not reserve a venue");
    expect(screen.getByText("Available for this period")).toBeInTheDocument();
  });

  it("SCRUM-64 AC4: clearing filters removes optional constraints", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Harbour Hall" });
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(searchVenues).toHaveBeenLastCalledWith({ facilities: [] }));
    expect(screen.getByLabelText("Expected attendance")).toHaveValue(null);
    expect(screen.getByLabelText("Event start (your local time)")).toHaveValue("");
  });

  it("SCRUM-64 AC5: an empty result has a readable no-match state", async () => {
    vi.mocked(searchVenues).mockResolvedValue({
      results: [],
      criteria: {},
      availability_integrated: true,
      booking_occupancy_integrated: true,
      holds_integrated: false,
      date_blocks_integrated: true,
      limitation: "Verify with Venue Staff.",
    });
    renderPage();
    expect(
      await screen.findByText("No venue matched the filters you entered."),
    ).toBeInTheDocument();
  });

  it("shows and retries search failures", async () => {
    vi.mocked(searchVenues).mockRejectedValueOnce(new Error("down"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not load venue search results",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Harbour Hall" })).toBeInTheDocument();
  });

  it("validates partial periods before sending a search", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Harbour Hall" });
    await userEvent.clear(screen.getByLabelText("Event end (your local time)"));
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter both event start and end");
    expect(searchVenues).toHaveBeenCalledTimes(1);
  });

  it("validates non-positive attendance before sending a search", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Harbour Hall" });
    await userEvent.clear(screen.getByLabelText("Expected attendance"));
    await userEvent.type(screen.getByLabelText("Expected attendance"), "0");
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("positive whole number");
  });

  it("SCRUM-68 AC1: adds against the event and refreshes the saved shortlist", async () => {
    renderPage();
    const button = await screen.findByRole("button", { name: "Shortlist Harbour Hall" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(addVenueToShortlist).toHaveBeenCalledWith(
      9,
      3,
      expect.objectContaining({ attendance: 60, layout: "THEATRE" }),
    );
    const saved = await screen.findByRole("region", { name: "Saved shortlist" });
    expect(await within(saved).findByRole("heading", { name: "Harbour Hall" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Shortlisted" })).toBeDisabled();
    expect(within(saved).getByRole("status")).toHaveTextContent("saved");
  });

  it("SCRUM-68 AC2: removes and refreshes the persisted shortlist", async () => {
    entries = [ENTRY];
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Remove Harbour Hall" }));
    expect(removeVenueFromShortlist).toHaveBeenCalledWith(9, 3);
    expect(await screen.findByText("No venues shortlisted yet.")).toBeInTheDocument();
  });

  it("SCRUM-68 AC3/4: shows unmet criteria and changed operational availability on reopen", async () => {
    entries = [
      {
        ...ENTRY,
        match: {
          ...MATCH,
          availability_status: "UNAVAILABLE",
          matches_recorded_requirements: false,
          criteria: [
            {
              key: "operational_status",
              label: "Operational status",
              result: "UNMET",
              message: "This venue is out of service.",
            },
          ],
        },
      },
    ];
    renderPage();
    const saved = await screen.findByRole("region", { name: "Saved shortlist" });
    expect(
      await within(saved).findByText("No longer available for these criteria"),
    ).toBeInTheDocument();
    expect(within(saved).getByText(/Not met: Operational status/)).toBeInTheDocument();
  });

  it("failed additions retain the shortlist and do not claim success", async () => {
    vi.mocked(addVenueToShortlist).mockRejectedValue(
      new ApiError(
        403,
        { detail: "Only the assigned coordinator may change this event's shortlist." },
        "Forbidden",
      ),
    );
    renderPage();
    const button = await screen.findByRole("button", { name: "Shortlist Harbour Hall" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("Only the assigned coordinator");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("No venues shortlisted yet.")).toBeInTheDocument();
  });

  it("failed removals keep the saved entry visible", async () => {
    entries = [ENTRY];
    vi.mocked(removeVenueFromShortlist).mockRejectedValue(new Error("network"));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Remove Harbour Hall" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not confirm this change");
    expect(screen.getByRole("button", { name: "Remove Harbour Hall" })).toBeInTheDocument();
  });

  it("uses the server's read-only decision for an unassigned coordinator or closed event", async () => {
    vi.mocked(getVenueShortlist).mockResolvedValue({
      event_id: 9,
      can_edit: false,
      entries: [ENTRY],
      availability_integrated: true,
      booking_occupancy_integrated: true,
      holds_integrated: false,
      date_blocks_integrated: true,
      limitation: "Verify with Venue Staff.",
    });
    renderPage();
    expect(await screen.findByText(/This shortlist is read-only/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Harbour Hall" })).toBeDisabled();
    expect(addVenueToShortlist).not.toHaveBeenCalled();
  });

  it("refreshes server state when a save succeeds but its response is lost", async () => {
    vi.mocked(addVenueToShortlist).mockImplementationOnce(async () => {
      entries = [ENTRY];
      throw new Error("response lost");
    });
    renderPage();
    const button = await screen.findByRole("button", { name: "Shortlist Harbour Hall" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not confirm this change");
    const saved = await screen.findByRole("region", { name: "Saved shortlist" });
    expect(await within(saved).findByRole("heading", { name: "Harbour Hall" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Shortlisted" })).toBeDisabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("standalone search does not fetch an event or expose shortlist actions", async () => {
    renderPage("/coordinator/venues");
    await screen.findByRole("heading", { name: "Harbour Hall" });
    expect(getEvent).not.toHaveBeenCalled();
    expect(getVenueShortlist).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Shortlist Harbour Hall" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    await waitFor(() => expect(searchVenues).toHaveBeenCalledTimes(2));
    expect(getVenueShortlist).not.toHaveBeenCalled();
  });

  it("explains a missing or inaccessible event", async () => {
    vi.mocked(getEvent).mockRejectedValue(new Error("not found"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("could not load this event");
    expect(searchVenues).not.toHaveBeenCalled();
  });

  it("SCRUM-68 AC4: a fresh page retains a saved entry and explains its new date block", async () => {
    entries = [ENTRY];
    const original = renderPage();
    const before = await screen.findByRole("region", { name: "Saved shortlist" });
    expect(await within(before).findByRole("heading", { name: "Harbour Hall" })).toBeInTheDocument();
    original.unmount();
    entries = [{
      ...ENTRY,
      match: {
        ...MATCH,
        availability_status: "UNAVAILABLE",
        matches_recorded_requirements: false,
        criteria: [{
          key: "date_blocks",
          label: "Recorded date-specific blocks",
          result: "UNMET",
          message: "Blocked: Air conditioning repair",
        }],
      },
    }];
    vi.mocked(searchVenues).mockResolvedValue({
      results: [], criteria: {}, availability_integrated: true,
      booking_occupancy_integrated: true, holds_integrated: false,
      date_blocks_integrated: true, limitation: "Search results do not reserve a venue.",
    });
    renderPage();
    const saved = await screen.findByRole("region", { name: "Saved shortlist" });
    expect(await within(saved).findByText("No longer available for these criteria")).toBeInTheDocument();
    expect(within(saved).getByText("Blocked: Air conditioning repair")).toBeInTheDocument();
    expect(await screen.findByText("No venue matched the filters you entered.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Harbour Hall" })).toBeEnabled();
  });

  it("shortlist load failures keep modification controls disabled", async () => {
    vi.mocked(getVenueShortlist).mockRejectedValueOnce(new Error("down"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not load this event's shortlist",
    );
    expect(screen.getByRole("button", { name: "Shortlist Harbour Hall" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Refresh shortlist" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Shortlist Harbour Hall" })).toBeEnabled());
  });

  it("G12: refresh shows booking and withdrawal changes without removing the saved entry", async () => {
    entries = [ENTRY];
    renderPage();
    const saved = await screen.findByRole("region", { name: "Saved shortlist" });
    expect(await within(saved).findByText("Available for this period")).toBeInTheDocument();
    const refresh = screen.getByRole("button", { name: "Refresh availability" });
    await waitFor(() => expect(refresh).toBeEnabled());
    entries = [{ ...ENTRY, match: { ...MATCH,
      availability_status: "UNAVAILABLE", matches_recorded_requirements: false,
      criteria: [{ key: "approved_bookings", label: "Approved bookings", result: "UNMET", message: "Conflicting event(s): 42" }],
    } }];
    vi.mocked(searchVenues).mockImplementation(async criteria => ({
      results: [], criteria, availability_integrated: true, booking_occupancy_integrated: true,
      holds_integrated: false, date_blocks_integrated: true, limitation: "Search results do not reserve a venue.",
    }));
    await userEvent.click(refresh);
    expect(await within(saved).findByText("Conflicting event(s): 42")).toBeInTheDocument();
    expect(within(saved).getByRole("heading", { name: "Harbour Hall" })).toBeInTheDocument();
    expect(await screen.findByText("No venue matched the filters you entered.")).toBeInTheDocument();

    entries = [ENTRY];
    vi.mocked(searchVenues).mockImplementation(async criteria => ({
      results: [MATCH], criteria, availability_integrated: true, booking_occupancy_integrated: true,
      holds_integrated: false, date_blocks_integrated: true, limitation: "Search results do not reserve a venue.",
    }));
    await waitFor(() => expect(refresh).toBeEnabled());
    await userEvent.click(refresh);
    expect(await within(saved).findByText("Available for this period")).toBeInTheDocument();
    expect(removeVenueFromShortlist).not.toHaveBeenCalled();
  });

  it("G12: returning focus refreshes an occupied saved venue despite the app's default", async () => {
    entries = [ENTRY];
    renderPage();
    const saved = await screen.findByRole("region", { name: "Saved shortlist" });
    expect(await within(saved).findByText("Available for this period")).toBeInTheDocument();
    focusManager.setFocused(false);
    entries = [{ ...ENTRY, match: { ...MATCH, availability_status: "UNAVAILABLE", matches_recorded_requirements: false } }];
    focusManager.setFocused(true);
    expect(await within(saved).findByText("No longer available for these criteria")).toBeInTheDocument();
    expect(getVenueShortlist).toHaveBeenCalledTimes(2);
  });

  it("G12: refusing a stale addition refreshes the old search result", async () => {
    renderPage();
    const add = await screen.findByRole("button", { name: "Shortlist Harbour Hall" });
    await waitFor(() => expect(add).toBeEnabled());
    vi.mocked(searchVenues).mockResolvedValue({
      results: [], criteria: {}, availability_integrated: true, booking_occupancy_integrated: true,
      holds_integrated: false, date_blocks_integrated: true, limitation: "Search results do not reserve a venue.",
    });
    vi.mocked(addVenueToShortlist).mockRejectedValue(new ApiError(400, { detail: "This venue no longer matches the saved search." }, "Stale match"));
    await userEvent.click(add);
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer matches");
    expect(await screen.findByText("No venue matched the filters you entered.")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("G12: missing dates show unverified availability even with booking integration enabled", async () => {
    vi.mocked(searchVenues).mockResolvedValue({
      results: [{ ...MATCH, venue: { ...MATCH.venue, location: "" }, availability_status: "UNVERIFIED",
        criteria: [{ key: "booking_availability", label: "Availability for an event period", result: "UNVERIFIED", message: "Enter event dates." }],
      }], criteria: {},
      availability_integrated: true, booking_occupancy_integrated: true, holds_integrated: false,
      date_blocks_integrated: true, limitation: "Enter event dates to check availability.",
    });
    renderPage("/coordinator/venues");
    expect(await screen.findByText("Availability not verified")).toBeInTheDocument();
    expect(screen.queryByText("Available for this period")).not.toBeInTheDocument();
    expect(screen.getByText(/Not checked: Availability for an event period/)).toBeInTheDocument();
    expect(screen.getByText(/Location not recorded/)).toBeInTheDocument();
  });

  it("G12: searching the same period refreshes results and saved entries", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Harbour Hall" });
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    await waitFor(() => expect(searchVenues).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(getVenueShortlist).toHaveBeenCalledTimes(2));
  });

  it("sends a changed start and removes a cleared layout constraint", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Harbour Hall" });
    fireEvent.change(screen.getByLabelText("Event start (your local time)"), { target: { value: "2027-03-01T00:00" } });
    await userEvent.selectOptions(screen.getByLabelText("Required room layout"), "");
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    await waitFor(() => expect(searchVenues).toHaveBeenCalledTimes(2));
    const latest = vi.mocked(searchVenues).mock.calls.at(-1)![0];
    expect(latest).not.toHaveProperty("layout");
    expect(Date.parse(latest.start!)).not.toBe(Date.parse(EVENT.preferred_start!));
  });

  it("refuses a reversed search period before making another API request", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Harbour Hall" });
    fireEvent.change(screen.getByLabelText("Event end (your local time)"), { target: { value: "2027-03-01T00:00" } });
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Event end must be after its start");
    expect(searchVenues).toHaveBeenCalledTimes(1);
  });

  it("shows the server's grouped validation messages for a refused shortlist addition", async () => {
    vi.mocked(addVenueToShortlist).mockRejectedValue(new ApiError(400, { detail: ["The room changed.", "Refresh availability."] }, "Refused"));
    renderPage();
    const add = await screen.findByRole("button", { name: "Shortlist Harbour Hall" });
    await waitFor(() => expect(add).toBeEnabled());
    await userEvent.click(add);
    expect(await screen.findByRole("alert")).toHaveTextContent("The room changed. Refresh availability.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

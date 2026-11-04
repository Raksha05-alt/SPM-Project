import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { listEventBookings, removeVenueSession, requestVenue } from "../../api/venueBookings";
import { listVenues } from "../../api/venues";
import type { EventRequest, Venue, VenueBooking } from "../../types";
import { VenuePlanner } from "./VenuePlanner";

vi.mock("../../api/venueBookings", () => ({ listEventBookings: vi.fn(), requestVenue: vi.fn(),
  withdrawVenue: vi.fn(), removeVenueSession: vi.fn() }));
vi.mock("../../api/venues", () => ({ listVenues: vi.fn() }));
vi.mock("../layouts/useLayouts", () => ({ useLayouts: () => ({ layouts: [] }), selectableLayouts: () => [] }));
const event = { id: 9, status: "PLANNING", preferred_start: "2027-06-08T02:00:00Z",
  preferred_end: "2027-06-08T04:00:00Z", expected_attendance: 120, required_layout: "" } as EventRequest;
const hall = { id: 1, name: "Main Hall", capacity: 120 } as Venue;
const room = { id: 2, name: "Workshop", capacity: 30 } as Venue;
const main = { id: 1, event: 9, session: 10, session_name: "Main programme", session_kind: "MAIN",
  session_active: true, venue: 1, venue_name: "Main Hall", status: "APPROVED", status_label: "Approved",
  starts_at: "2027-06-08T02:00:00Z", ends_at: "2027-06-08T04:00:00Z", attendance: 120,
  layout: "", layout_name: "", required_facilities: [], accessibility_notes: "", event_name: "Conference",
  organisation_name: "Acme", wheelchair_access_required: false, status_changed_at: "2026-11-04T01:00:00Z",
  requested_by_name: "Cora", requested_at: "2026-11-04T01:00:00Z", decided_by_name: "Vera",
  decided_at: "2026-11-04T01:00:00Z", decision_reason: "" } satisfies VenueBooking;
const breakout = { ...main, id: 2, session: 11, session_name: "Breakout A", session_kind: "BREAKOUT",
  venue: 2, venue_name: "Workshop", attendance: 30, required_facilities: ["Projector"],
  wheelchair_access_required: true, accessibility_notes: "Step free" } as VenueBooking;
function show() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <VenuePlanner event={event} />
  </QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listEventBookings).mockResolvedValue([main, breakout]);
  vi.mocked(listVenues).mockResolvedValue([hall, room]);
  vi.mocked(requestVenue).mockResolvedValue({ detail: "Request sent", booking: breakout });
});

it("SCRUM-87 AC1/2: new breakout has its own name and attendance; main attendance follows the event", async () => {
  const user = userEvent.setup(); show();
  await screen.findByText("Workshop");
  expect(screen.getByLabelText("Attendance")).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Session", { exact: true }), "NEW");
  expect(screen.getByLabelText("Attendance")).toBeEnabled();
  await user.type(screen.getByLabelText("Session name"), "Breakout B");
  await user.type(screen.getByLabelText("Attendance"), "25");
  await user.selectOptions(screen.getByLabelText("Venue", { exact: true }), "2");
  await user.click(screen.getByRole("button", { name: "Send request to Venue Staff" }));
  await waitFor(() => expect(requestVenue).toHaveBeenCalledWith(9, expect.objectContaining({
    session_kind: "BREAKOUT", session_name: "Breakout B", attendance: 25, venue: 2,
  })));
});

it("SCRUM-87 AC5: reuses stable session and requirements for an explicit staff-reviewed replacement", async () => {
  const user = userEvent.setup(); show();
  await screen.findByText("Workshop");
  await user.selectOptions(screen.getByLabelText("Session", { exact: true }), "11");
  expect(screen.getByLabelText("Attendance")).toHaveValue(30);
  expect(screen.getByLabelText("Required facilities")).toHaveValue("Projector");
  expect(screen.getByLabelText("Wheelchair access required")).toBeChecked();
  await user.click(screen.getByLabelText(/Replace Workshop/));
  await user.selectOptions(screen.getByLabelText("Venue", { exact: true }), "1");
  await user.click(screen.getByRole("button", { name: "Send request to Venue Staff" }));
  await waitFor(() => expect(requestVenue).toHaveBeenCalledWith(9, expect.objectContaining({
    session_id: 11, replaces_id: 2, attendance: 30, required_facilities: ["Projector"],
  })));
  expect(screen.getByRole("row", { name: /Main programme Main Hall/ })).toContainHTML("Approved");
});

it("SCRUM-87 AC5: removes a withdrawn breakout explicitly, retaining its booking history", async () => {
  vi.mocked(listEventBookings).mockResolvedValue([main, { ...breakout, status: "WITHDRAWN", status_label: "Withdrawn" }]);
  const confirmation = vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(removeVenueSession).mockResolvedValue({});
  const user = userEvent.setup(); show();
  await user.click(await screen.findByRole("button", { name: "Remove session Breakout A" }));
  await waitFor(() => expect(removeVenueSession).toHaveBeenCalledWith(9, 11));
  expect(screen.getByRole("row", { name: /Breakout A Workshop/ })).toContainHTML("Withdrawn");
  confirmation.mockRestore();
});

it("SCRUM-87 AC5: cancelling removal makes no write; a refused removal shows the server message", async () => {
  vi.mocked(listEventBookings).mockResolvedValue([{ ...breakout, status: "REJECTED" }]);
  const confirmation = vi.spyOn(window, "confirm").mockReturnValue(false);
  const user = userEvent.setup(); show();
  const remove = await screen.findByRole("button", { name: "Remove session Breakout A" });
  await user.click(remove); expect(removeVenueSession).not.toHaveBeenCalled();
  confirmation.mockReturnValue(true);
  vi.mocked(removeVenueSession).mockRejectedValue(new Error("Session changed; reload"));
  await user.click(remove);
  expect(await screen.findByRole("alert")).toHaveTextContent("Session changed; reload");
  confirmation.mockRestore();
});

it("SCRUM-87 AC2: names invalid session input and preserves the form after refusal", async () => {
  vi.mocked(requestVenue).mockRejectedValue(new ApiError(400, { detail: "Invalid session", session_name: ["Choose a unique name"] }, "Invalid session"));
  const user = userEvent.setup(); show(); await screen.findByText("Workshop");
  await user.selectOptions(screen.getByLabelText("Session", { exact: true }), "NEW");
  await user.type(screen.getByLabelText("Session name"), "Breakout A");
  await user.click(screen.getByRole("button", { name: "Send request to Venue Staff" }));
  expect(await screen.findByText("Choose a unique name")).toBeVisible();
  expect(screen.getByLabelText("Session name")).toHaveValue("Breakout A");
});

it("SCRUM-87 AC1: session selection lists each stable identity once and omits removed sessions", async () => {
  vi.mocked(listEventBookings).mockResolvedValue([main, breakout, { ...breakout, id: 3, status: "WITHDRAWN" },
    { ...breakout, id: 4, session: 12, session_name: "Removed", session_active: false }]);
  const user = userEvent.setup(); show();
  await screen.findAllByText("Breakout A");
  const select = screen.getByLabelText("Session", { exact: true });
  expect(within(select).getAllByRole("option", { name: "Breakout A" })).toHaveLength(1);
  expect(within(select).queryByRole("option", { name: "Removed" })).not.toBeInTheDocument();
  await user.selectOptions(select, "11"); await user.selectOptions(select, "MAIN");
  expect(screen.getByLabelText("Attendance")).toHaveValue(120);
  expect(screen.getByLabelText("Attendance")).toBeDisabled();
});

it("SCRUM-87 AC7: refreshed main attendance follows an event edit while breakout attendance stays local", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { rerender } = render(<QueryClientProvider client={client}><VenuePlanner event={event} /></QueryClientProvider>);
  await screen.findByText("Workshop");
  expect(screen.getByLabelText("Attendance")).toHaveValue(120);
  rerender(<QueryClientProvider client={client}><VenuePlanner event={{ ...event, expected_attendance: 121 }} /></QueryClientProvider>);
  expect(screen.getByLabelText("Attendance")).toHaveValue(121);
  await userEvent.selectOptions(screen.getByLabelText("Session", { exact: true }), "11");
  expect(screen.getByLabelText("Attendance")).toHaveValue(30);
});

it("SCRUM-86: automatically links a replacement to the disrupted session booking", async () => {
  vi.mocked(listEventBookings).mockResolvedValue([main, { ...breakout, status: "DISRUPTED", status_label: "Disrupted" }]);
  const user = userEvent.setup(); show();
  await screen.findByText("Workshop");
  await user.selectOptions(screen.getByLabelText("Session", { exact: true }), "11");
  await user.selectOptions(screen.getByLabelText("Venue", { exact: true }), "1");
  await user.click(screen.getByRole("button", { name: "Send request to Venue Staff" }));
  await waitFor(() => expect(requestVenue).toHaveBeenCalledWith(9, expect.objectContaining({
    session_id: 11, replaces_id: 2, attendance: 30,
  })));
  expect(screen.getByRole("row", { name: /Breakout A Workshop/ })).toContainHTML("Disrupted");
});

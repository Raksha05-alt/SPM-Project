import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthContext } from "../auth/AuthContext";
import { RequireRole } from "../auth/RequireRole";
import * as api from "../api/availability";
import { listVenues } from "../api/venues";
import { VenueAvailability } from "./VenueAvailability";
import type { Role, Venue } from "../types";

vi.mock("../api/venues", () => ({ listVenues: vi.fn() }));
vi.mock("../api/availability", () => ({
  getAvailability: vi.fn(), getBlocks: vi.fn(), getBlockHistory: vi.fn(),
  saveBlock: vi.fn(), removeBlock: vi.fn(), findAvailableVenues: vi.fn(),
}));
const block = { id: 7, reason: "Maintenance", starts_at: "2026-11-02T10:00:00+08:00", ends_at: "2026-11-02T12:00:00+08:00" };
function renderPage(role: Role = "VENUE_STAFF") {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <AuthContext.Provider value={{ user: { id: 1, email: "test@example.com", first_name: "Test", last_name: "User", role, role_label: role, organisation: null, organisation_name: null, landing_path: "/" }, loading: false, signIn: vi.fn(), signOut: vi.fn() }}>
      <MemoryRouter><RequireRole roles={["COORDINATOR", "VENUE_STAFF"]}><VenueAvailability /></RequireRole></MemoryRouter>
    </AuthContext.Provider>
  </QueryClientProvider>);
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listVenues).mockResolvedValue([{ id: 1, name: "Harbour Hall" } as Venue]);
  vi.mocked(api.getBlocks).mockResolvedValue([block]);
  vi.mocked(api.getBlockHistory).mockResolvedValue([]);
  vi.mocked(api.getAvailability).mockResolvedValue({ venue_id: 1, status: "blocked", available: false, timezone: "Asia/Singapore", starts_at: block.starts_at, ends_at: block.ends_at, blocks: [block] });
  vi.mocked(api.findAvailableVenues).mockResolvedValue([]);
});
async function selectVenue() {
  await screen.findByRole("option", { name: "Harbour Hall" });
  fireEvent.change(screen.getByLabelText("Venue"), { target: { value: "1" } });
  await screen.findByText("Maintenance");
}
it("checks Singapore periods and displays block reasons; coordinators have no edit controls", async () => {
  renderPage("COORDINATOR"); await selectVenue();
  fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2026-11-02T10:00" } });
  fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2026-11-02T12:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Check availability" }));
  expect(await screen.findByRole("region", { name: "Availability result" })).toHaveTextContent("blocked");
  expect(api.getAvailability).toHaveBeenCalledWith(1, block.starts_at, block.ends_at);
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
});
it("saves, edits, removes and refreshes blocks", async () => {
  vi.mocked(api.saveBlock).mockResolvedValue(block);
  vi.mocked(api.removeBlock).mockResolvedValue(undefined);
  renderPage(); await selectVenue();
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Repairs" } });
  fireEvent.change(screen.getByLabelText("Block start"), { target: { value: "2026-11-02T10:00" } });
  fireEvent.change(screen.getByLabelText("Block end"), { target: { value: "2026-11-02T12:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Save block" }));
  await screen.findByText("Block saved.");
  expect(api.saveBlock).toHaveBeenCalledWith(1, { ...block, id: undefined, reason: "Repairs" }, undefined);
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Reason")).toHaveValue("Maintenance");
  fireEvent.click(screen.getByRole("button", { name: "Save block" }));
  await screen.findByText("Block updated.");
  expect(api.saveBlock).toHaveBeenLastCalledWith(1, { reason: "Maintenance", starts_at: block.starts_at, ends_at: block.ends_at }, 7);
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await screen.findByText("Block removed.");
  expect(api.removeBlock).toHaveBeenCalledWith(1, 7);
  expect(vi.mocked(api.getBlocks).mock.calls.length).toBeGreaterThan(1);
});
it("retains input after a failed save", async () => {
  vi.mocked(api.saveBlock).mockRejectedValue(new Error("offline"));
  renderPage(); await selectVenue();
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "Save block" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
  expect(screen.getByLabelText("Reason")).toHaveValue("Maintenance");
});
it("searches available venues and shows an empty result", async () => {
  renderPage("COORDINATOR");
  fireEvent.change(screen.getByLabelText("Search start"), { target: { value: "2026-11-02T10:00" } });
  fireEvent.change(screen.getByLabelText("Search end"), { target: { value: "2026-11-02T12:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Find available venues" }));
  await screen.findByText("No venues available for this period.");
  expect(api.findAvailableVenues).toHaveBeenCalledWith(block.starts_at, block.ends_at);
});
it.each<Role>(["ATTENDEE", "ORGANISER"])("refuses direct calendar access for %s", async role => {
  renderPage(role);
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Venue availability" })).not.toBeInTheDocument());
  expect(listVenues).not.toHaveBeenCalled();
});

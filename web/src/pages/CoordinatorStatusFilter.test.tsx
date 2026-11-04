import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { fetchMyEvents } from "../api/events";
import type { AssignedEventRow, EventStatus } from "../types";
import { CoordinatorMyEvents } from "./CoordinatorMyEvents";
vi.mock("../api/events", () => ({ fetchMyEvents: vi.fn(), approveEvent: vi.fn() }));
const rows = [
  { id: 1, name: "Main planning", status: "PLANNING", status_label: "Planning", requires_action: true },
  { id: 2, name: "Confirmed conference", status: "CONFIRMED", status_label: "Confirmed", requires_action: false },
  { id: 3, name: "Approved workshop", status: "APPROVED", status_label: "Approved", requires_action: true },
] as AssignedEventRow[];
function show() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><CoordinatorMyEvents /></MemoryRouter>
  </QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchMyEvents).mockImplementation(async (statuses: EventStatus[] = []) =>
    statuses.length ? rows.filter(row => statuses.includes(row.status)) : rows);
});
it("SCRUM-57 AC1: one and multiple statuses refetch and show only matches", async () => {
  const user = userEvent.setup(); show();
  await screen.findByRole("link", { name: "Approved workshop" });
  await user.click(screen.getByRole("checkbox", { name: "Planning" }));
  await waitFor(() => expect(screen.queryByRole("link", { name: "Approved workshop" })).not.toBeInTheDocument());
  expect(screen.getByRole("link", { name: "Main planning" })).toBeVisible();
  await user.click(screen.getByRole("checkbox", { name: "Confirmed" }));
  expect(await screen.findByRole("link", { name: "Confirmed conference" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Main planning" })).toBeVisible();
  expect(fetchMyEvents).toHaveBeenLastCalledWith(["PLANNING", "CONFIRMED"]);
  expect(screen.queryByRole("checkbox", { name: "Draft" })).not.toBeInTheDocument();
});
it("SCRUM-57 AC2/4: no matches shows an empty state; clearing restores the permitted list", async () => {
  const user = userEvent.setup(); show();
  await screen.findByRole("link", { name: "Main planning" });
  await user.click(screen.getByRole("checkbox", { name: "Completed" }));
  expect(await screen.findByText("No events match the selected statuses.")).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(await screen.findByRole("link", { name: "Approved workshop" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Main planning" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Completed" })).not.toBeChecked();
});
it("SCRUM-57 AC4: unchecking the last status also clears the filter", async () => {
  const user = userEvent.setup(); show(); await screen.findByRole("link", { name: "Main planning" });
  const planning = screen.getByRole("checkbox", { name: "Planning" });
  await user.click(planning); await user.click(planning);
  expect(await screen.findByRole("link", { name: "Approved workshop" })).toBeVisible();
  expect(fetchMyEvents).toHaveBeenLastCalledWith([]);
});
it("SCRUM-57: a failed filtered request can be cleared without hiding the controls", async () => {
  vi.mocked(fetchMyEvents).mockImplementation(async (statuses: EventStatus[] = []) => {
    if (statuses.length) throw new Error("Network unavailable");
    return rows;
  });
  const user = userEvent.setup(); show(); await screen.findByRole("link", { name: "Main planning" });
  await user.click(screen.getByRole("checkbox", { name: "Planning" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("We could not load your events.");
  await user.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(await screen.findByRole("link", { name: "Main planning" })).toBeVisible();
});

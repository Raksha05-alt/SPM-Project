import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { approveRevisedEquipment, approveNoEquipment, getEquipmentPlan, listEquipmentPlans, reserveEquipment, type EquipmentPlan } from "../api/equipmentPlans";
import { EquipmentPlanPage } from "./EquipmentPlan";

vi.mock("../api/equipmentPlans", () => ({ approveRevisedEquipment: vi.fn(), approveNoEquipment: vi.fn(), getEquipmentPlan: vi.fn(), listEquipmentPlans: vi.fn(), reserveEquipment: vi.fn() }));
const auth = { user: { id: 2, role: "TECH_SUPPORT" } };
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
const BASE: EquipmentPlan = {
  event: { id: 9, name: "Partner Summit", status: "PLANNING", starts_at: "2027-03-01T02:00:00Z", ends_at: "2027-03-01T04:00:00Z" }, revision: 3,
  requests: [{ id: 4, event: 9, equipment_type: 1, equipment_type_name: "Projector", quantity: 3, technical_requirements: "HDMI", status: "REQUESTED", status_label: "Requested", requested_by_name: "Cora", requested_at: "2026-11-01T01:00:00Z" }],
  reservations: [], technical_approval: null,
};
function setup(value = BASE, path = "/equipment/plans/9", denied = false) {
  vi.mocked(getEquipmentPlan).mockImplementation(() => denied ? Promise.reject(new Error("Forbidden")) : Promise.resolve(value));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/equipment/plans" element={<EquipmentPlanPage />} /><Route path="/equipment/plans/:id" element={<EquipmentPlanPage />} /></Routes></MemoryRouter></QueryClientProvider>);
  return { user: userEvent.setup(), client, invalidate };
}
beforeEach(() => { vi.clearAllMocks(); auth.user.role = "TECH_SUPPORT"; });

describe("SCRUM-16 equipment reservation screen", () => {
  it("U16-01 shows requested quantities and requirements", async () => {
    setup(); const row = await screen.findByRole("region", { name: "Projector" });
    expect(row).toHaveTextContent("3 × Projector"); expect(row).toHaveTextContent("HDMI");
    expect(screen.getByRole("link", { name: "Check availability" })).toHaveAttribute("href", "/equipment/availability/9");
    expect(screen.getByText("No reservations recorded.")).toBeVisible();
  });
  it("U16-02 reserves the displayed request and refreshes dependent reads", async () => {
    const { user, invalidate } = setup(); vi.mocked(reserveEquipment).mockResolvedValue(BASE);
    await user.click(await screen.findByRole("button", { name: "Reserve 3 × Projector" }));
    expect(reserveEquipment).toHaveBeenCalledWith(4, 3);
    expect(await screen.findByRole("status")).toHaveTextContent("coordinator has been notified");
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["equipment-availability"] }));
  });
  it("U16-03 reports stock refusal and reloads", async () => {
    const { user } = setup(); vi.mocked(reserveEquipment).mockRejectedValue(new Error("Only 2 available."));
    await user.click(await screen.findByRole("button", { name: /Reserve 3/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only 2 available.");
    await waitFor(() => expect(vi.mocked(getEquipmentPlan).mock.calls.length).toBeGreaterThan(1));
  });
  it("U16-04 disables repeat submissions while pending", async () => {
    const { user } = setup(); vi.mocked(reserveEquipment).mockReturnValue(new Promise(() => {}));
    const button = await screen.findByRole("button", { name: /Reserve 3/ }); await user.click(button);
    expect(button).toBeDisabled(); expect(screen.getByRole("button", { name: "Refresh plan" })).toBeDisabled();
  });
  it.each(["COORDINATOR", "EVENT_ORGANISER"])("U16-05 hides staff writes for %s", async (role) => {
    auth.user.role = role; setup(); await screen.findByRole("heading", { name: /Equipment plan:/ });
    expect(screen.queryByRole("button", { name: /Reserve 3/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to event" })).toHaveAttribute("href", "/coordinator/events/9");
  });
  it.each(["COMPLETED", "CANCELLED", "REJECTED"] as const)("U16-06 hides reservation for %s", async (status) => {
    setup({ ...BASE, event: { ...BASE.event, status } }); await screen.findByRole("heading", { name: /Equipment plan:/ });
    expect(screen.queryByRole("button", { name: /Reserve 3/ })).not.toBeInTheDocument();
  });
  it("U16-07 hides actions without dates", async () => {
    setup({ ...BASE, event: { ...BASE.event, starts_at: null, ends_at: null } }); await screen.findByRole("heading", { name: /Equipment plan:/ });
    expect(screen.getByText(/Not set – Not set/)).toBeVisible(); expect(screen.queryByRole("button", { name: /Reserve 3/ })).not.toBeInTheDocument();
  });
  it("U16-08 displays retained reservations and technical approval", async () => {
    setup({ ...BASE, requests: [{ ...BASE.requests[0], status: "RESERVED", status_label: "Reserved", technical_requirements: "" }], reservations: [{ id: 8, request: 4, quantity: 3, starts_at: BASE.event.starts_at!, ends_at: BASE.event.ends_at!, status: "ACTIVE", reserved_by_name: "Taylor", reserved_at: "2026-11-02T01:00:00Z", released_by_name: null, released_at: null, release_reason: "" }], technical_approval: { id: 2, revision: 3, no_equipment_required: false, notes: "", approved_by_name: "Taylor", approved_at: "2026-11-02T01:00:00Z" } });
    expect(await screen.findByRole("region", { name: "Reservation history" })).toHaveTextContent("Reserved by Taylor");
    expect(screen.getByText(/Technical arrangements approved by Taylor/)).toBeVisible();
    expect(screen.getByText("No additional technical requirements.")).toBeVisible();
  });
  it("U16-09 requires explicit no-equipment acknowledgement and notes", async () => {
    const { user } = setup({ ...BASE, requests: [] }); await user.click(await screen.findByRole("button", { name: "Approve no equipment required" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("enter your review notes"); expect(approveNoEquipment).not.toHaveBeenCalled();
    await user.click(screen.getByRole("checkbox")); await user.type(screen.getByLabelText("Technical review notes"), "  Venue provides everything  ");
    vi.mocked(approveNoEquipment).mockResolvedValue(BASE); await user.click(screen.getByRole("button", { name: "Approve no equipment required" }));
    expect(approveNoEquipment).toHaveBeenCalledWith(9, 3, "Venue provides everything"); expect(await screen.findByRole("status")).toHaveTextContent("no equipment required");
  });
  it("U16-10 shows technical-review refusal", async () => {
    const { user } = setup({ ...BASE, requests: [] }); await user.click(await screen.findByRole("checkbox")); await user.type(screen.getByLabelText("Technical review notes"), "Checked");
    vi.mocked(approveNoEquipment).mockRejectedValue(new Error("Equipment was requested meanwhile.")); await user.click(screen.getByRole("button", { name: "Approve no equipment required" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("requested meanwhile");
  });
  it("U16-11 handles loading and lost access", async () => {
    setup(BASE, "/equipment/plans/9", true); expect(screen.getByText("Loading equipment plan…")).toBeVisible();
    expect(await screen.findByRole("alert")).toHaveTextContent("still have access");
  });
  it("U16-12 offers events requiring technical review", async () => {
    vi.mocked(listEquipmentPlans).mockResolvedValue([{ id: 9, name: "Partner Summit" }]); const { user } = setup(BASE, "/equipment/plans");
    await user.selectOptions(await screen.findByLabelText("Event"), "9"); expect(await screen.findByRole("heading", { name: /Equipment plan: Partner/ })).toBeVisible();
  });
  it("U16-13 displays an empty plan list", async () => {
    vi.mocked(listEquipmentPlans).mockResolvedValue([]); setup(BASE, "/equipment/plans"); expect(await screen.findByText("No events are awaiting technical arrangements.")).toBeVisible();
  });
  it("U16-14 reports plan-list failure", async () => {
    vi.mocked(listEquipmentPlans).mockRejectedValue(new Error("down")); setup(BASE, "/equipment/plans"); expect(await screen.findByRole("alert")).toHaveTextContent("could not load the equipment plans");
  });
  it("U16-16 displays release history without offering another reservation", async () => {
    setup({ ...BASE, requests: [{ ...BASE.requests[0], status: "WITHDRAWN", status_label: "Withdrawn" }], reservations: [{ id: 8, request: 4, quantity: 3, starts_at: BASE.event.starts_at!, ends_at: BASE.event.ends_at!, status: "RELEASED", reserved_by_name: "Taylor", reserved_at: "2026-11-02T01:00:00Z", released_by_name: "Riley", released_at: "2026-11-02T02:00:00Z", release_reason: "No longer needed" }] });
    expect(await screen.findByRole("region", { name: "Reservation history" })).toHaveTextContent("Released by Riley");
    expect(screen.getByText(/No longer needed/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Reserve 3/ })).not.toBeInTheDocument();
  });
  it("U16-15 manual refresh fetches current records", async () => {
    const { user } = setup(); await user.click(await screen.findByRole("button", { name: "Refresh plan" }));
    await waitFor(() => expect(vi.mocked(getEquipmentPlan).mock.calls.length).toBeGreaterThan(1));
  });
});

it("U75-01 technical staff can approve a revised plan with retained units", async () => {
  const value = { ...BASE, requests: [{ ...BASE.requests[0], status: "RESERVED" as const, status_label: "Reserved" }] };
  vi.mocked(approveRevisedEquipment).mockResolvedValue(value);
  const { user, invalidate } = setup(value);
  await user.click(await screen.findByRole("button", { name: "Approve revised equipment plan" }));
  expect(approveRevisedEquipment).toHaveBeenCalledWith(9, 3);
  expect(await screen.findByRole("status")).toHaveTextContent("Revised technical arrangements approved");
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["equipment-plan"] }));
});

it("U75-02 displays retained changes with values actor and time", async () => {
  auth.user.role = "COORDINATOR";
  setup({ ...BASE, history: [{ id: 1, action: "AMENDED", before: { quantity: 5, technical_requirements: "HDMI", status: "REQUESTED" }, after: { quantity: 3, technical_requirements: "USB-C", status: "RESERVED" }, actor: "Cora Coordinator", created_at: "2026-11-02T01:00:00Z" }] });
  const history = await screen.findByRole("region", { name: "Request change history" });
  await waitFor(() => expect(history).toHaveTextContent("AMENDED by Cora Coordinator on"));
  expect(history).toHaveTextContent("Quantity: 5 to 3");
  expect(history).toHaveTextContent("Technical requirements: HDMI to USB-C");
  expect(history).toHaveTextContent("Status: REQUESTED to RESERVED");
  expect(history).toHaveTextContent(new Date("2026-11-02T01:00:00Z").toLocaleString("en-SG"));
});

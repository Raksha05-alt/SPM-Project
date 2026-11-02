import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { amendEquipment, withdrawEquipment } from "../../api/equipmentPlans";
import type { EquipmentRequest } from "../../types";
import { EquipmentAmendment } from "./EquipmentAmendment";
vi.mock("../../api/equipmentPlans", () => ({ amendEquipment: vi.fn(), withdrawEquipment: vi.fn() }));
const item = { id: 4, quantity: 5, technical_requirements: "HDMI", status: "RESERVED" } as EquipmentRequest;
function setup() {
  const refresh = vi.fn(async () => {});
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}><EquipmentAmendment item={item} revision={7} refresh={refresh} /></QueryClientProvider>);
  return { user: userEvent.setup(), refresh };
}
beforeEach(() => vi.clearAllMocks());
it("sends exact revised values and revision then refreshes", async () => {
  vi.mocked(amendEquipment).mockResolvedValue({} as never);
  const { user, refresh } = setup();
  await user.click(screen.getByRole("button", { name: "Amend request" }));
  await user.clear(screen.getByLabelText("Revised quantity"));
  await user.type(screen.getByLabelText("Revised quantity"), "3");
  await user.clear(screen.getByLabelText("Revised technical requirements"));
  await user.type(screen.getByLabelText("Revised technical requirements"), "USB-C");
  await user.click(screen.getByRole("button", { name: "Save amendment" }));
  expect(amendEquipment).toHaveBeenCalledWith(4, 7, 3, "USB-C");
  expect(await screen.findByRole("status")).toHaveTextContent("Technical Support");
  expect(refresh).toHaveBeenCalled();
});
it("requires confirmation and allows keeping the request", async () => {
  const { user } = setup();
  await user.click(screen.getByRole("button", { name: "Withdraw request" }));
  expect(withdrawEquipment).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Keep request" }));
  expect(screen.queryByRole("button", { name: "Confirm withdrawal" })).not.toBeInTheDocument();
});
it("withdraws the displayed request with its revision", async () => {
  vi.mocked(withdrawEquipment).mockResolvedValue({} as never);
  const { user, refresh } = setup();
  await user.click(screen.getByRole("button", { name: "Withdraw request" }));
  await user.click(screen.getByRole("button", { name: "Confirm withdrawal" }));
  expect(withdrawEquipment).toHaveBeenCalledWith(4, 7);
  expect(await screen.findByRole("status")).toHaveTextContent("withdrawn");
  expect(refresh).toHaveBeenCalled();
});
it("shows stale refusal and refreshes current data", async () => {
  vi.mocked(withdrawEquipment).mockRejectedValue(new Error("Reload the plan."));
  const { user, refresh } = setup();
  await user.click(screen.getByRole("button", { name: "Withdraw request" }));
  await user.click(screen.getByRole("button", { name: "Confirm withdrawal" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Reload the plan");
  expect(refresh).toHaveBeenCalled();
});

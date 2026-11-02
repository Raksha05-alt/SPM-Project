import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { releaseEquipment, type EquipmentReservation } from "../../api/equipmentPlans";
import { EquipmentRelease } from "./EquipmentRelease";
vi.mock("../../api/equipmentPlans", () => ({ releaseEquipment: vi.fn() }));
const ROW = { id: 8, request: 4, quantity: 3, status: "ACTIVE" } as EquipmentReservation;
function setup(row=ROW) {
  const refresh=vi.fn(async () => {});
  render(<QueryClientProvider client={new QueryClient()}><EquipmentRelease reservation={row} revision={3} refresh={refresh}/></QueryClientProvider>);
  return {user:userEvent.setup(),refresh};
}
beforeEach(()=>vi.clearAllMocks());
it("U77-R01 requires a reason before releasing the displayed quantity",async()=>{
 const {user}=setup();expect(screen.getByText(/Release these 3 units/)).toBeVisible();
 await user.click(screen.getByRole("button"));expect(screen.getByRole("alert")).toHaveTextContent("Enter a reason");expect(releaseEquipment).not.toHaveBeenCalled();
});
it("U77-R02 sends exact identity revision and trimmed reason, then refreshes",async()=>{
 const {user,refresh}=setup();vi.mocked(releaseEquipment).mockResolvedValue({} as never);
 await user.type(screen.getByLabelText("Release reason"),"  Not needed  ");await user.click(screen.getByRole("button"));
 expect(releaseEquipment).toHaveBeenCalledWith(8,3,"Not needed");expect(await screen.findByRole("status")).toHaveTextContent("Equipment released");expect(refresh).toHaveBeenCalled();expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("U77-R03 shows stale-release refusal and refreshes",async()=>{
 const {user,refresh}=setup();vi.mocked(releaseEquipment).mockRejectedValue(new Error("The plan changed."));
 await user.type(screen.getByLabelText("Release reason"),"Returned");await user.click(screen.getByRole("button"));
 expect(await screen.findByRole("alert")).toHaveTextContent("plan changed");expect(refresh).toHaveBeenCalled();
});
it("U77-R04 blocks repeat release while pending",async()=>{
 const {user}=setup();vi.mocked(releaseEquipment).mockReturnValue(new Promise(()=>{}));await user.type(screen.getByLabelText("Release reason"),"Returned");const button=screen.getByRole("button");await user.click(button);expect(button).toBeDisabled();
});
it("U77-R05 hides release for historical rows",()=>{
 setup({...ROW,status:"RELEASED"});expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

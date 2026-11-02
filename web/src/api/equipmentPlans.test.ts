import { beforeEach, expect, it, vi } from "vitest";
import { request } from "./client";
import { approveNoEquipment, getEquipmentPlan, listEquipmentPlans, reserveEquipment, releaseEquipment } from "./equipmentPlans";
vi.mock("./client", () => ({ request: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
it("A16-01 reads the scoped plan and technical review list", () => {
  getEquipmentPlan(9); listEquipmentPlans();
  expect(request).toHaveBeenCalledWith("/api/events/9/equipment-plan/");
  expect(request).toHaveBeenCalledWith("/api/equipment/plans/");
});
it("A16-02 sends reservation revision and explicit no-equipment acknowledgement", () => {
  reserveEquipment(4, 3); approveNoEquipment(9, 3, "Reviewed");
  expect(request).toHaveBeenCalledWith("/api/equipment/requests/4/reserve/", { method: "POST", body: { expected_revision: 3 } });
  expect(request).toHaveBeenCalledWith("/api/events/9/approve-no-equipment/", { method: "POST", body: { expected_revision: 3, acknowledged: true, notes: "Reviewed" } });
});

it("A77-R01 sends the reservation revision and release reason", () => {
  releaseEquipment(8, 3, "Returned");
  expect(request).toHaveBeenCalledWith("/api/equipment/reservations/8/release/", { method: "POST", body: { expected_revision: 3, reason: "Returned" } });
});

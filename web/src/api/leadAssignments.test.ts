import { beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "./client";
import { assignCoordinator, getLeadEvent, listAssignments, listCoordinators, listUnassignedEvents } from "./leadAssignments";
vi.mock("./client", () => ({ request: vi.fn() }));
describe("Lead allocation API", () => {
  beforeEach(() => vi.clearAllMocks());
  it("sends the selected coordinator and observed revision", () => {
    assignCoordinator(9, 3, 4);
    expect(request).toHaveBeenCalledWith("/api/events/9/assign-coordinator/", {
      method: "POST", body: { coordinator_id: 3, expected_revision: 4 },
    });
  });
  it("uses the Lead queues, roster and detail endpoints", () => {
    listUnassignedEvents(); listCoordinators(); getLeadEvent(9);
    expect(request).toHaveBeenCalledWith("/api/events/unassigned/");
    expect(request).toHaveBeenCalledWith("/api/events/coordinators/");
    expect(request).toHaveBeenCalledWith("/api/events/9/");
  });
  it("sends explicit active/supervisor filters", () => {
    listAssignments(false, true); listAssignments(true, false);
    expect(request).toHaveBeenCalledWith("/api/events/assignments/?active=true");
    expect(request).toHaveBeenCalledWith("/api/events/assignments/?active=false&supervised_by=me");
  });
});

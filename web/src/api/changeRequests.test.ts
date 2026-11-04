import { expect, it, vi } from "vitest";
import { decideChange, getChangeImpact, listChangeRequests, requestChange } from "./changeRequests";
import { request } from "./client";

vi.mock("./client", () => ({ request: vi.fn() }));

it("reads an event's SCRUM-20 change requests", () => {
  listChangeRequests(4);
  expect(request).toHaveBeenCalledWith("/api/events/4/change-requests/");
});

it("posts a change request with its proposed values", () => {
  const input = { description: "More guests", reason: "Partners joined", proposed_values: { expected_attendance: 150 } };
  requestChange(4, input);
  expect(request).toHaveBeenCalledWith("/api/events/4/change-requests/", { method: "POST", body: input });
});

it("reads the SCRUM-59/78 impact of a change request", () => {
  getChangeImpact(7);
  expect(request).toHaveBeenCalledWith("/api/change-requests/7/impact/");
});

it("posts the SCRUM-78 decision with its reason", () => {
  decideChange(7, "REJECT", "No room");
  expect(request).toHaveBeenCalledWith("/api/change-requests/7/decide/", {
    method: "POST",
    body: { decision: "REJECT", reason: "No room" },
  });
});

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

it("calls the SCRUM-80 apply, keep-original, history and review endpoints", async () => {
  const { applyChange, keepOriginal, getChangeHistory, listArrangementReviews, decideArrangement } =
    await import("./changeRequests");
  applyChange(7);
  expect(request).toHaveBeenCalledWith("/api/change-requests/7/apply/", { method: "POST" });
  keepOriginal(7, "Agreed");
  expect(request).toHaveBeenCalledWith("/api/change-requests/7/keep-original/", {
    method: "POST",
    body: { reason: "Agreed" },
  });
  getChangeHistory(7);
  expect(request).toHaveBeenCalledWith("/api/change-requests/7/history/");
  listArrangementReviews();
  expect(request).toHaveBeenCalledWith("/api/arrangement-reviews/?status=PENDING");
  decideArrangement(3, "ACCOMMODATED", "Fine");
  expect(request).toHaveBeenCalledWith("/api/arrangement-reviews/3/decide/", {
    method: "POST",
    body: { outcome: "ACCOMMODATED", reason: "Fine" },
  });
});

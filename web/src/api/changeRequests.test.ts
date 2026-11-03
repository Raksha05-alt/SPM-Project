import { expect, it, vi } from "vitest";
import { listChangeRequests, requestChange } from "./changeRequests";
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

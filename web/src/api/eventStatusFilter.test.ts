import { beforeEach, expect, it, vi } from "vitest";
import { request } from "./client";
import { fetchMyEvents } from "./events";
vi.mock("./client", () => ({ request: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
it("SCRUM-57 client contract: repeated status keys encode the selected set", () => {
  fetchMyEvents(["PLANNING", "CONFIRMED"]);
  expect(request).toHaveBeenCalledWith("/api/events/mine/?status=PLANNING&status=CONFIRMED");
});
it("SCRUM-57 client contract: clearing and the default omit the query", () => {
  fetchMyEvents([]); fetchMyEvents();
  expect(request).toHaveBeenCalledTimes(2);
  expect(request).toHaveBeenNthCalledWith(1, "/api/events/mine/");
  expect(request).toHaveBeenNthCalledWith(2, "/api/events/mine/");
});

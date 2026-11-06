import { expect, it, vi } from "vitest";
import { request } from "./client";
import { getChangeHistory } from "./changeHistory";

vi.mock("./client", () => ({ request: vi.fn() }));

it("reads the SCRUM-60 change history", () => {
  getChangeHistory(4);
  expect(request).toHaveBeenCalledWith("/api/events/4/change-history/");
});

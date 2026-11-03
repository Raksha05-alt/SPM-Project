import { beforeEach, expect, it, vi } from "vitest";
import { request } from "./client";
import { getUnreadCount, listNotifications, markNotificationRead } from "./notifications";

vi.mock("./client", () => ({ request: vi.fn() }));

beforeEach(() => vi.mocked(request).mockReset());

it("calls the SCRUM-82 notification endpoints", () => {
  listNotifications();
  getUnreadCount();
  markNotificationRead(5);
  expect(request).toHaveBeenNthCalledWith(1, "/api/notifications/");
  expect(request).toHaveBeenNthCalledWith(2, "/api/notifications/unread-count/");
  expect(request).toHaveBeenNthCalledWith(3, "/api/notifications/5/read/", { method: "POST" });
});

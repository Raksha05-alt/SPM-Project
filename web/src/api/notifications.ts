import { request } from "./client";
import type { AppNotification } from "../types";

/** SCRUM-82 AC1 - the signed-in user's notices, most recent first. */
export const listNotifications = () => request<AppNotification[]>("/api/notifications/");

/** SCRUM-82 AC2 - how many are still unread. */
export const getUnreadCount = () =>
  request<{ unread: number }>("/api/notifications/unread-count/");

/** SCRUM-82 AC2 - mark one notice read. Repeating it changes nothing. */
export const markNotificationRead = (id: number) =>
  request<{ notification: AppNotification; unread: number }>(
    `/api/notifications/${id}/read/`,
    { method: "POST" },
  );

import { request } from "./client";

/** SCRUM-79 AC5 / SCRUM-82 - which event, what happened, when, and whether it was read. */
export interface AppNotification {
  id: number;
  event: number;
  event_name: string;
  kind?: string;
  kind_label: string;
  message: string;
  created_at: string;
  read_at: string | null;
  is_read: boolean;
}

export const listNotifications = () => request<AppNotification[]>("/api/notifications/");

export const getUnreadCount = () =>
  request<{ unread: number }>("/api/notifications/unread-count/");

export const markNotificationRead = (id: number) =>
  request<AppNotification & { unread: number }>(`/api/notifications/${id}/read/`, {
    method: "POST",
  });

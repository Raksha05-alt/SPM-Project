import { request } from "./client";
import type { AssignmentNotification } from "../types";

export const listNotifications = () =>
  request<AssignmentNotification[]>("/api/notifications/");

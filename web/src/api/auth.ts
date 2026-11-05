import { request } from "./client";
import type { User } from "../types";

export const login = (email: string, password: string) =>
  request<User>("/api/auth/login/", { method: "POST", body: { email, password } });

export const logout = () => request<void>("/api/auth/logout/", { method: "POST" });

export const fetchMe = () => request<User>("/api/auth/me/");

/** SCRUM-2 - the editable contact details of the signed-in user. */
export type AccountChanges = Partial<Pick<User, "first_name" | "last_name" | "email">>;

/** SCRUM-2 AC2 - save the signed-in user's own contact details. */
export const updateMe = (changes: AccountChanges) =>
  request<User & { changed_fields: string[] }>("/api/auth/me/", {
    method: "PATCH",
    body: changes,
  });

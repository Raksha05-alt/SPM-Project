import { request } from "./client";
import type { User } from "../types";

export const login = (email: string, password: string) =>
  request<User>("/api/auth/login/", { method: "POST", body: { email, password } });

export const logout = () => request<void>("/api/auth/logout/", { method: "POST" });

export const fetchMe = () => request<User>("/api/auth/me/");

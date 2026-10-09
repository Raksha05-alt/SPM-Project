import { request } from "./client";
import type { User } from "../types";

/** SCRUM-2 - the signed-in user's own account, including the phone number. */
export interface Account extends User {
  phone: string;
}

export interface AccountUpdate {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
}

export const getAccount = () => request<Account>("/api/auth/me/");

export const updateAccount = (changes: AccountUpdate) =>
  request<Account>("/api/auth/me/", { method: "PATCH", body: changes });

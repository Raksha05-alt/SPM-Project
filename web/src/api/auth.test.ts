import { expect, it, vi } from "vitest";
import { request } from "./client";
import { updateMe } from "./auth";

vi.mock("./client", () => ({ request: vi.fn() }));

it("SCRUM-2 saves only the signed-in user's own details", () => {
  updateMe({ email: "ada@acme.example" });
  expect(request).toHaveBeenCalledWith("/api/auth/me/", {
    method: "PATCH",
    body: { email: "ada@acme.example" },
  });
});

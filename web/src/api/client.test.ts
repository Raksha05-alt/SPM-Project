import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, readCookie, request } from "./client";

function mockFetch(status: number, body: unknown) {
  const response = {
    status,
    ok: status >= 200 && status < 300,
    text: async () => (body === null ? "" : JSON.stringify(body)),
  };
  const spy = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("api client", () => {
  it("returns the parsed body on success", async () => {
    mockFetch(200, { status: "ok" });

    await expect(request("/api/health/")).resolves.toEqual({ status: "ok" });
  });

  it("sends the CSRF token on unsafe requests only", async () => {
    document.cookie = "csrftoken=token-123";
    const spy = mockFetch(201, { id: 1 });

    await request("/api/events/", { method: "POST", body: { name: "x" } });
    await request("/api/events/");

    const postHeaders = spy.mock.calls[0][1].headers;
    const getHeaders = spy.mock.calls[1][1].headers;
    expect(postHeaders["X-CSRFToken"]).toBe("token-123");
    expect(getHeaders["X-CSRFToken"]).toBeUndefined();
  });

  it("US-02.2 AC2: surfaces the fields that are blocking submission", async () => {
    mockFetch(400, {
      detail: "This request cannot be submitted yet.",
      missing_fields: ["name", "expected_attendance"],
    });

    await expect(request("/api/events/1/submit/", { method: "POST" })).rejects.toSatisfy(
      (error: unknown) =>
        error instanceof ApiError &&
        error.status === 400 &&
        error.missingFields.includes("expected_attendance"),
    );
  });

  it("treats 204 as an empty success", async () => {
    mockFetch(204, null);

    await expect(request("/api/events/1/", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("reads a named cookie and ignores others", () => {
    document.cookie = "csrftoken=abc123";

    expect(readCookie("csrftoken")).toBe("abc123");
    expect(readCookie("sessionid")).toBeNull();
  });
});

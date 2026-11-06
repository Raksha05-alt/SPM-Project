import ReactDOM, { type Root } from "react-dom/client";
import { act, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

it("US-6 startup mounts the real providers and redirects an expired session to sign-in", async () => {
  const node = document.createElement("div");
  node.id = "root";
  document.body.append(node);
  window.history.replaceState({}, "", "/");
  let root: Root | undefined;
  const createRoot = ReactDOM.createRoot;
  const spy = vi.spyOn(ReactDOM, "createRoot").mockImplementation((container, options) => {
    root = createRoot(container, options);
    return root;
  });
  const fetch = vi.fn(async (path: string) => new Response(JSON.stringify(
    path === "/api/auth/csrf/" ? {} : { detail: "Session expired." },
  ), { status: path === "/api/auth/csrf/" ? 200 : 401 }));
  vi.stubGlobal("fetch", fetch);
  try {
    await act(async () => { await import("./main"); });
    expect(await screen.findByRole("heading", { name: "Sign in to ConnectSphere" })).toBeVisible();
    expect(window.location.pathname).toBe("/login");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/auth/me/", expect.objectContaining({ credentials: "same-origin" }));
  } finally {
    await act(async () => { root?.unmount(); });
    spy.mockRestore();
    vi.unstubAllGlobals();
    node.remove();
    window.history.replaceState({}, "", "/");
  }
});

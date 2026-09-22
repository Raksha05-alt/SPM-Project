import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as events from "../api/events";
import type { EventRequest } from "../types";
import { EventRequestForm } from "./EventRequestForm";

vi.mock("../api/events");
const saved = {
  id: 42, name: "Workshop", purpose: "", status: "DRAFT", status_label: "Draft",
  status_description: "Private draft", is_editable: true,
  preferred_start: "2027-01-15T01:30:00Z", preferred_end: null,
} as EventRequest;

function open(path = "/organiser/requests/new") {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><Routes>
      <Route path="/organiser/requests/new" element={<EventRequestForm />} />
      <Route path="/organiser/requests/:id" element={<EventRequestForm />} />
      <Route path="/organiser" element={<p>Draft list</p>} />
    </Routes></MemoryRouter>
  </QueryClientProvider>);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(events.getEvent).mockResolvedValue(saved);
});

describe("SCRUM-8 draft form", () => {
  it("saves an empty form without submitting it", async () => {
    vi.mocked(events.createDraft).mockResolvedValue(saved);
    open();
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(events.createDraft).toHaveBeenCalledWith(expect.objectContaining({ name: "", preferred_start: null })));
    expect(screen.queryByRole("button", { name: "Send to ConnectSphere" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Delete draft" })).toBeInTheDocument();
  });

  it("reopens local date/time unchanged and saves edits", async () => {
    vi.mocked(events.updateDraft).mockResolvedValue({ ...saved, name: "Updated" });
    open("/organiser/requests/42");
    const name = await screen.findByLabelText("Event name");
    expect(name).toHaveValue("Workshop");
    const date = new Date(saved.preferred_start!);
    const expected = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    expect(screen.getByLabelText("Preferred start")).toHaveValue(expected);
    await userEvent.clear(name);
    await userEvent.type(name, "Updated");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(events.updateDraft).toHaveBeenCalledWith(42, expect.objectContaining({ name: "Updated" })));
    expect(await screen.findByRole("status")).toHaveTextContent("Draft saved.");
  });

  it("deletes only after confirmation and returns to the list", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.mocked(events.deleteDraft).mockResolvedValue(undefined);
    open("/organiser/requests/42");
    await userEvent.click(await screen.findByRole("button", { name: "Delete draft" }));
    expect(events.deleteDraft).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Delete draft" }));
    expect(await screen.findByText("Draft list")).toBeInTheDocument();
    expect(events.deleteDraft).toHaveBeenCalledWith(42);
    confirm.mockRestore();
  });

  it("does not show an editable form when opening a draft is refused", async () => {
    vi.mocked(events.getEvent).mockRejectedValue(new Error("Forbidden"));
    open("/organiser/requests/42");
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load this draft.");
    expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
  });
});

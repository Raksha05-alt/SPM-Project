import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { EventRequestForm } from "./EventRequestForm";
import { getEvent, submitEvent, updateDraft } from "../api/events";

vi.mock("../api/events", () => ({
  getEvent: vi.fn(), submitEvent: vi.fn(), updateDraft: vi.fn(), createDraft: vi.fn(),
}));
const draft = {
  id: 1, name: "Conference", purpose: "Briefing", status: "DRAFT",
  status_label: "Draft", status_description: "Draft request", is_editable: true,
  preferred_start: "2030-01-01T02:00:00Z", preferred_end: "2030-01-01T04:00:00Z",
  expected_attendance: 10, submitted_at: null,
};
function mount() {
  return render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
    <MemoryRouter initialEntries={["/organiser/requests/1"]}>
      <Routes><Route path="/organiser/requests/:id" element={<EventRequestForm />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>);
}
describe("request submission", () => {
  it("keeps confirmation and timestamp visible and locks the submitted form", async () => {
    const submitted = {...draft, status: "SUBMITTED", status_label: "Submitted", is_editable: false,
      submitted_at: "2026-09-23T12:00:00Z"};
    vi.mocked(getEvent).mockResolvedValue(draft as never);
    vi.mocked(updateDraft).mockResolvedValue(draft as never);
    vi.mocked(submitEvent).mockImplementation(async () => {
      vi.mocked(getEvent).mockResolvedValue(submitted as never);
      return submitted as never;
    });
    mount();
    await screen.findByDisplayValue("Conference");
    await userEvent.click(screen.getByRole("button", {name: "Send to ConnectSphere"}));
    expect(await screen.findByText("Your request has been sent to ConnectSphere.")).toBeInTheDocument();
    expect(screen.getByText(/Submitted to ConnectSphere on/)).toBeInTheDocument();
    expect(screen.getByLabelText("Event name")).toBeDisabled();
    expect(screen.queryByRole("button", {name: "Send to ConnectSphere"})).not.toBeInTheDocument();
  });
});

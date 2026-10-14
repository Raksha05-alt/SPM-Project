import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getEvent } from "../../api/events";
import { listCoordinatorOptions } from "../../api/lead";
import { planningEvent } from "../../components/planning/fixtures";
import { LeadEventDetail } from "./LeadEventDetail";

vi.mock("../../api/events", () => ({ getEvent: vi.fn() }));
vi.mock("../../api/lead", () => ({
  listCoordinatorOptions: vi.fn(),
  assignCoordinator: vi.fn(),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/lead/events/9"]}>
        <Routes>
          <Route path="/lead/events/:id" element={<LeadEventDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCoordinatorOptions).mockResolvedValue([]);
});

describe("Week 7 CR5 - the Lead reviews basic event information", () => {
  it("shows the event, its supervising Lead and the assignment history", async () => {
    vi.mocked(getEvent).mockResolvedValue({
      ...planningEvent({
        required_layout_label: "Theatre",
        assigned_by_name: "Leah Lead",
        assigned_at: "2026-10-02T01:00:00Z",
      }),
      assignment_history: [
        {
          id: 1,
          previous_coordinator_name: null,
          coordinator_name: "Cora Coordinator",
          changed_by_name: "Leah Lead",
          changed_at: "2026-10-02T01:00:00Z",
        },
      ],
    } as never);

    renderPage();

    expect(await screen.findByRole("heading", { name: "Partner Summit" })).toBeInTheDocument();
    expect(screen.getByText("Theatre")).toBeInTheDocument();
    expect(screen.getByText(/Assigned by Leah Lead/)).toBeInTheDocument();
    expect(screen.getByText(/Cora Coordinator · by Leah Lead/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reassign this event" })).toBeInTheDocument();
  });

  it("offers no assignment on a closed event", async () => {
    vi.mocked(getEvent).mockResolvedValue(
      planningEvent({ status: "COMPLETED", status_label: "Completed" }),
    );

    renderPage();

    await screen.findByRole("heading", { name: "Partner Summit" });
    expect(screen.queryByRole("region", { name: "Assignment" })).not.toBeInTheDocument();
  });
});

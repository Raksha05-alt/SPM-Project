import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listOrganiserEvents, type OrganiserEvent } from "../api/organiser";
import { OrganiserDashboard } from "./OrganiserDashboard";

vi.mock("../api/organiser", () => ({ listOrganiserEvents: vi.fn() }));

function row(overrides: Partial<OrganiserEvent>): OrganiserEvent {
  return {
    id: 1,
    name: "Partner Summit",
    preferred_start: "2026-10-20T01:00:00Z",
    expected_attendance: 120,
    status: "PLANNING",
    status_label: "Planning",
    status_description: "Arrangements are being made.",
    ...overrides,
  } as OrganiserEvent;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OrganiserDashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SCRUM-45 / SCRUM-57 organiser dashboard status filter", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: lists every event request when no status is chosen", async () => {
    vi.mocked(listOrganiserEvents).mockResolvedValue([
      row({ id: 1, name: "Partner Summit" }),
      row({ id: 2, name: "Board Retreat", status: "DRAFT", status_label: "Draft" }),
    ]);
    renderPage();
    expect(await screen.findByText("Partner Summit")).toBeInTheDocument();
    expect(screen.getByText("Board Retreat")).toBeInTheDocument();
    expect(listOrganiserEvents).toHaveBeenCalledWith([]);
  });

  it("AC2: filters the list by the chosen status", async () => {
    vi.mocked(listOrganiserEvents).mockImplementation(async (statuses = []) =>
      statuses.includes("CONFIRMED")
        ? [row({ id: 3, name: "Gala Dinner", status: "CONFIRMED", status_label: "Confirmed" })]
        : [row({ id: 1, name: "Partner Summit" })],
    );
    renderPage();
    expect(await screen.findByText("Partner Summit")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Filter by status"), "CONFIRMED");
    expect(await screen.findByText("Gala Dinner")).toBeInTheDocument();
    expect(screen.queryByText("Partner Summit")).not.toBeInTheDocument();
    expect(listOrganiserEvents).toHaveBeenLastCalledWith(["CONFIRMED"]);
  });

  it("AC3: says when no event has the chosen status", async () => {
    vi.mocked(listOrganiserEvents).mockImplementation(async (statuses = []) =>
      statuses.length ? [] : [row({ id: 1 })],
    );
    renderPage();
    await screen.findByText("Partner Summit");
    await userEvent.selectOptions(screen.getByLabelText("Filter by status"), "CANCELLED");
    expect(await screen.findByText("No event requests have this status.")).toBeInTheDocument();
  });

  it("shows an error when the list cannot be loaded", async () => {
    vi.mocked(listOrganiserEvents).mockRejectedValue(new Error("offline"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not load your event requests.",
    );
  });
});

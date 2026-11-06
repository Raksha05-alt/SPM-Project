import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listOrganiserEvents } from "../api/events";
import type { EventRequest } from "../types";
import { OrganiserDashboard } from "./OrganiserDashboard";

vi.mock("../api/events", () => ({ listOrganiserEvents: vi.fn() }));

function row(overrides: Partial<EventRequest>): EventRequest {
  return {
    id: 1,
    name: "Partner Summit",
    status: "SUBMITTED",
    status_label: "Submitted",
    status_description: "Waiting for review.",
    preferred_start: "2027-03-01T02:00:00Z",
    expected_attendance: 60,
    coordinator_name: null,
    updated_at: "2026-11-01T03:00:00Z",
    ...overrides,
  } as EventRequest;
}

function mockLists(drafts: EventRequest[], submitted: EventRequest[]) {
  vi.mocked(listOrganiserEvents).mockImplementation((group) =>
    Promise.resolve(group === "drafts" ? drafts : submitted),
  );
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

describe("OrganiserDashboard (SCRUM-45/48)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("SCRUM-45 AC1 - shows each request with its date, status and coordinator", async () => {
    mockLists(
      [],
      [
        row({ id: 1, name: "Partner Summit", coordinator_name: "Cora Coordinator" }),
        row({ id: 2, name: "Board Dinner", preferred_start: null }),
      ],
    );
    renderPage();

    const sent = await screen.findByRole("region", { name: "Sent to ConnectSphere" });
    expect(within(sent).getByRole("link", { name: "Partner Summit" })).toHaveAttribute(
      "href",
      "/organiser/requests/1",
    );
    expect(within(sent).getByText("Coordinator: Cora Coordinator")).toBeInTheDocument();
    expect(within(sent).getByText("Coordinator: not yet assigned")).toBeInTheDocument();
    expect(within(sent).getByText(/No date yet/)).toBeInTheDocument();
    expect(within(sent).getAllByText("Submitted")).toHaveLength(2);
    expect(listOrganiserEvents).toHaveBeenCalledWith("drafts");
    expect(listOrganiserEvents).toHaveBeenCalledWith("submitted");
  });

  it("SCRUM-48 AC1/AC3 - drafts are grouped apart, each with when it was last saved", async () => {
    mockLists(
      [row({ id: 3, name: "", status: "DRAFT", status_label: "Draft" })],
      [row({ id: 1 })],
    );
    renderPage();

    const drafts = await screen.findByRole("region", { name: "Drafts" });
    expect(within(drafts).getByRole("link", { name: "(untitled draft)" })).toHaveAttribute(
      "href",
      "/organiser/requests/3",
    );
    const saved = new Date("2026-11-01T03:00:00Z").toLocaleString("en-SG");
    expect(within(drafts).getByText(`Last saved ${saved}`)).toBeInTheDocument();
    expect(within(drafts).queryByText("Partner Summit")).not.toBeInTheDocument();
  });

  it("SCRUM-48 AC4 - no drafts shows an empty state even with submitted requests", async () => {
    mockLists([], [row({ id: 1 })]);
    renderPage();

    expect(await screen.findByText("You have no saved drafts.")).toBeInTheDocument();
    expect(screen.getByText("Partner Summit")).toBeInTheDocument();
  });

  it("SCRUM-45 AC3 - no requests at all shows an empty state, not an error", async () => {
    mockLists([], []);
    renderPage();

    expect(await screen.findByText(/You have no event requests yet/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an error when the list cannot be loaded", async () => {
    vi.mocked(listOrganiserEvents).mockRejectedValue(new Error("down"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("could not load");
  });
});

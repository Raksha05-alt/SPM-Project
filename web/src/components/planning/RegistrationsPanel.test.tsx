import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { fetchRegistrations } from "../../api/planning";
import { RegistrationsPanel } from "./RegistrationsPanel";

vi.mock("../../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/planning")>()),
  fetchRegistrations: vi.fn(),
}));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RegistrationsPanel eventId={9} />
    </QueryClientProvider>,
  );
}

describe("SCRUM-14 AC5 / SCRUM-19 AC4 registrations for the coordinator", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC5: shows the counts and each registration's status, withdrawn included", async () => {
    vi.mocked(fetchRegistrations).mockResolvedValue({
      capacity: 2,
      registered_count: 2,
      waitlist_count: 1,
      places_left: 0,
      registrations: [
        {
          id: 1,
          full_name: "Ann Attendee",
          email: "ann@example.com",
          accessibility_needs: "Wheelchair",
          status: "REGISTERED",
          status_display: "Registered",
          registered_at: "2026-10-01T01:00:00Z",
          waitlisted_at: null,
          withdrawn_at: null,
        },
        {
          id: 2,
          full_name: "Wes Waiting",
          email: "wes@example.com",
          accessibility_needs: "",
          status: "WAITLISTED",
          status_display: "On waiting list",
          registered_at: null,
          waitlisted_at: "2026-10-02T01:00:00Z",
          withdrawn_at: null,
        },
        {
          id: 3,
          full_name: "Will Withdrawn",
          email: "will@example.com",
          accessibility_needs: "",
          status: "WITHDRAWN",
          status_display: "Withdrawn",
          registered_at: "2026-10-01T01:00:00Z",
          waitlisted_at: null,
          withdrawn_at: "2026-10-03T01:00:00Z",
        },
      ],
    });

    renderPanel();

    expect(await screen.findByText("Ann Attendee")).toBeInTheDocument();
    expect(fetchRegistrations).toHaveBeenCalledWith(9);
    expect(screen.getByText("Registered", { selector: "dt" }).nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Waiting list").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Places left").nextSibling).toHaveTextContent("0");
    const withdrawn = screen.getByText("Will Withdrawn").closest("tr")!;
    expect(within(withdrawn).getByText("Withdrawn")).toBeInTheDocument();
    expect(screen.getByText("On waiting list")).toBeInTheDocument();
  });

  it("shows an empty state when no one has registered", async () => {
    vi.mocked(fetchRegistrations).mockResolvedValue({
      capacity: 50,
      registered_count: 0,
      waitlist_count: 0,
      places_left: 50,
      registrations: [],
    });

    renderPanel();

    expect(await screen.findByText("No one has registered yet.")).toBeInTheDocument();
  });

  it("shows the API's refusal", async () => {
    vi.mocked(fetchRegistrations).mockRejectedValue(
      new ApiError(403, null, "Only the client and the assigned coordinator can see this."),
    );

    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only the client and the assigned coordinator can see this.",
    );
  });
});

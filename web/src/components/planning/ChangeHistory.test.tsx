import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { fetchHistory } from "../../api/planning";
import { ChangeHistory } from "./ChangeHistory";

vi.mock("../../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/planning")>()),
  fetchHistory: vi.fn(),
}));

function renderHistory() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChangeHistory eventId={9} />
    </QueryClientProvider>,
  );
}

describe("SCRUM-60 change history", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1/AC2: lists the field, old and new values, who and when, marking significant changes", async () => {
    vi.mocked(fetchHistory).mockResolvedValue([
      {
        id: 2,
        field: "expected_attendance",
        previous_value: "120",
        new_value: "200",
        changed_by: 2,
        changed_by_name: "Cora Coordinator",
        changed_at: "2026-10-01T02:00:00Z",
        significant: true,
      },
      {
        id: 1,
        field: "purpose",
        previous_value: "Briefing",
        new_value: "Annual briefing",
        changed_by: 2,
        changed_by_name: "Cora Coordinator",
        changed_at: "2026-09-30T02:00:00Z",
        significant: false,
      },
    ]);

    renderHistory();

    expect(await screen.findByText("Expected attendance")).toBeInTheDocument();
    expect(fetchHistory).toHaveBeenCalledWith(9);
    expect(screen.getByText("120 → 200")).toBeInTheDocument();
    expect(screen.getByText("Briefing → Annual briefing")).toBeInTheDocument();
    const when = new Date("2026-10-01T02:00:00Z").toLocaleString("en-SG");
    expect(screen.getByText(`Cora Coordinator · ${when}`)).toBeInTheDocument();
    expect(screen.getAllByText("Significant")).toHaveLength(1);
  });

  it("AC3: shows an empty state when nothing has changed", async () => {
    vi.mocked(fetchHistory).mockResolvedValue([]);

    renderHistory();

    expect(await screen.findByText("No changes have been recorded yet.")).toBeInTheDocument();
  });

  it("AC4: shows the API's refusal", async () => {
    vi.mocked(fetchHistory).mockRejectedValue(
      new ApiError(403, null, "Change history is restricted to ConnectSphere staff."),
    );

    renderHistory();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Change history is restricted to ConnectSphere staff.",
    );
  });
});

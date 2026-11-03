import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getChangeHistory, type FieldChange } from "../api/changeHistory";
import { ChangeHistory } from "./ChangeHistory";

vi.mock("../api/changeHistory", () => ({ getChangeHistory: vi.fn() }));

function change(overrides: Partial<FieldChange> = {}): FieldChange {
  return {
    id: 2,
    field: "expected_attendance",
    field_label: "Expected attendance",
    before: 120,
    after: 150,
    before_display: "120",
    after_display: "150",
    values_recorded: true,
    actor_name: "Cora Coordinator",
    source: "EVENT_EDIT",
    source_label: "Event details edited",
    changed_at: "2026-11-03T02:00:00Z",
    ...overrides,
  };
}

function renderHistory() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChangeHistory eventId={9} />
    </QueryClientProvider>,
  );
}

describe("SCRUM-60 change history", () => {
  beforeEach(() => vi.mocked(getChangeHistory).mockReset());

  it("AC1/AC2: shows each change's field, values, user and time in the order the API sends (newest first)", async () => {
    vi.mocked(getChangeHistory).mockResolvedValue({
      event: 9,
      changes: [
        change(),
        change({ id: 1, field: "name", field_label: "Name", before_display: "Summit", after_display: "Partner Summit", changed_at: "2026-11-03T01:00:00Z" }),
      ],
    });
    renderHistory();

    const rows = await screen.findAllByRole("row");
    expect(getChangeHistory).toHaveBeenCalledWith(9);
    expect(within(rows[1]).getByText("Expected attendance")).toBeInTheDocument();
    expect(within(rows[1]).getByText("120")).toBeInTheDocument();
    expect(within(rows[1]).getByText("150")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Cora Coordinator")).toBeInTheDocument();
    expect(rows[1].querySelector("time")).toHaveAttribute("datetime", "2026-11-03T02:00:00Z");
    expect(within(rows[2]).getByText("Partner Summit")).toBeInTheDocument();
  });

  it("shows earlier edits as not recorded, never as invented values", async () => {
    vi.mocked(getChangeHistory).mockResolvedValue({
      event: 9,
      changes: [change({ values_recorded: false, before_display: "Not recorded", after_display: "Not recorded", actor_name: null })],
    });
    renderHistory();

    expect(await screen.findAllByText("Not recorded")).toHaveLength(2);
    expect(screen.getByText("Unknown user")).toBeInTheDocument();
  });

  it("offers no way to edit or delete an entry", async () => {
    vi.mocked(getChangeHistory).mockResolvedValue({ event: 9, changes: [change()] });
    renderHistory();
    await screen.findByText("Expected attendance");

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.mocked(getChangeHistory).mockResolvedValue({ event: 9, changes: [] });
    renderHistory();
    expect(await screen.findByText("No changes have been recorded.")).toBeInTheDocument();
  });

  it("says so when the history cannot be loaded, and retries", async () => {
    vi.mocked(getChangeHistory)
      .mockRejectedValueOnce(new Error("forbidden"))
      .mockResolvedValue({ event: 9, changes: [] });
    renderHistory();

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load the change history.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No changes have been recorded.")).toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import {
  createLayout,
  deleteLayout,
  listLayouts,
  reinstateLayout,
  retireLayout,
  updateLayout,
} from "../api/layouts";
import { SEED_LAYOUTS } from "../api/__mocks__/layouts";
import type { LayoutType } from "../types";
import { RoomLayouts } from "./RoomLayouts";

const CABARET: LayoutType = {
  ...SEED_LAYOUTS[0],
  code: "CABARET",
  name: "Cabaret",
  description: "Round tables",
  sort_order: 6,
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RoomLayouts />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function row(name: string) {
  return screen.getByRole("cell", { name }).closest("tr") as HTMLElement;
}

describe("RoomLayouts (SCRUM-91)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listLayouts).mockResolvedValue([
      ...SEED_LAYOUTS,
      { ...CABARET, is_active: false },
    ]);
  });

  it("lists every layout with its code, name and status", async () => {
    renderPage();

    expect(await screen.findByRole("cell", { name: "Theatre" })).toBeInTheDocument();
    expect(within(row("Theatre")).getByText("THEATRE")).toBeInTheDocument();
    expect(within(row("Theatre")).getByText("Active")).toBeInTheDocument();
    expect(within(row("Cabaret")).getByText("Retired")).toBeInTheDocument();
    expect(within(row("Cabaret")).getByText("Round tables")).toBeInTheDocument();
  });

  it("AC1: adds a layout with a code, name and description", async () => {
    vi.mocked(createLayout).mockResolvedValue({ ...CABARET, code: "BOOTH", name: "Booth" });
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("Code"), "BOOTH");
    await user.type(screen.getByLabelText("Name"), "Booth");
    await user.type(screen.getByLabelText("Description"), "Small stands");
    await user.click(screen.getByRole("button", { name: "Add layout" }));

    expect(createLayout).toHaveBeenCalledWith({
      code: "BOOTH",
      name: "Booth",
      description: "Small stands",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Added Booth.");
    expect(screen.getByLabelText("Code")).toHaveValue("");
  });

  it("AC1: shows why a new layout was refused beside the field", async () => {
    vi.mocked(createLayout).mockRejectedValue(
      new ApiError(400, { code: ["A layout with this code already exists."] }, "Bad request"),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("Code"), "THEATRE");
    await user.type(screen.getByLabelText("Name"), "Another");
    await user.click(screen.getByRole("button", { name: "Add layout" }));

    expect(await screen.findByText("A layout with this code already exists.")).toBeInTheDocument();
  });

  it("AC2: renames a layout; its code is shown but cannot be edited", async () => {
    vi.mocked(updateLayout).mockResolvedValue({ ...SEED_LAYOUTS[1], name: "Lecture theatre" });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Edit Theatre" }));
    const name = screen.getByLabelText("Name for THEATRE");
    await user.clear(name);
    await user.type(name, "Lecture theatre");
    await user.type(screen.getByLabelText("Description for THEATRE"), "Tiered rows");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(updateLayout).toHaveBeenCalledWith("THEATRE", {
      name: "Lecture theatre",
      description: "Tiered rows",
    });
    expect(screen.queryByLabelText(/Code for/)).not.toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent("Saved Lecture theatre.");
  });

  it("AC3: deletes an unused layout only after confirming", async () => {
    vi.mocked(deleteLayout).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Delete Banquet" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(deleteLayout).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete Banquet" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(deleteLayout).toHaveBeenCalledWith("BANQUET");
    expect(await screen.findByRole("status")).toHaveTextContent("Deleted Banquet.");
  });

  it("AC3: a layout in use is not deleted, says where it is used and offers retiring", async () => {
    vi.mocked(deleteLayout).mockRejectedValue(
      new ApiError(
        409,
        {
          detail: "Theatre is in use and cannot be deleted. Retire it instead.",
          usage: { venues: 2, event_requests: 1, venue_bookings: 0 },
          can_retire: true,
        },
        "Theatre is in use and cannot be deleted. Retire it instead.",
      ),
    );
    vi.mocked(retireLayout).mockResolvedValue({ ...SEED_LAYOUTS[1], is_active: false });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Delete Theatre" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Theatre is in use and cannot be deleted.");
    expect(alert).toHaveTextContent("Used by 2 venues, 1 event request.");

    await user.click(within(alert).getByRole("button", { name: "Retire Theatre instead" }));

    expect(retireLayout).toHaveBeenCalledWith("THEATRE");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Retired Theatre. It stays on existing records but can no longer be chosen.",
    );
  });

  it("AC3: retires an active layout and reinstates a retired one", async () => {
    vi.mocked(retireLayout).mockResolvedValue({ ...SEED_LAYOUTS[0], is_active: false });
    vi.mocked(reinstateLayout).mockResolvedValue({ ...CABARET, is_active: true });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Retire Classroom" }));
    expect(retireLayout).toHaveBeenCalledWith("CLASSROOM");

    await user.click(screen.getByRole("button", { name: "Reinstate Cabaret" }));
    expect(reinstateLayout).toHaveBeenCalledWith("CABARET");
    expect(await screen.findByRole("status")).toHaveTextContent("Cabaret can be chosen again.");
  });

  it("explains when the catalogue cannot be loaded", async () => {
    vi.mocked(listLayouts).mockRejectedValue(new ApiError(403, null, "Forbidden"));

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not load the room layouts.",
    );
  });
});

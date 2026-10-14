import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { createLayout, deleteLayout, listLayouts, updateLayout } from "../../api/layouts";
import { LayoutCatalogue } from "./LayoutCatalogue";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LayoutCatalogue />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const theatre = { id: 2, code: "THEATRE", name: "Theatre", description: "", is_active: true };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listLayouts).mockResolvedValue([theatre]);
});

describe("Week 7 clarification - Venue Staff maintain room layouts", () => {
  it("adds a layout", async () => {
    vi.mocked(createLayout).mockResolvedValue({ ...theatre, id: 9, code: "U_SHAPE", name: "U-shape" });

    renderPage();
    await screen.findByText("Theatre");
    await userEvent.type(screen.getByLabelText("Code"), "U_SHAPE");
    await userEvent.type(screen.getByLabelText("Name"), "U-shape");
    await userEvent.click(screen.getByRole("button", { name: "Add layout" }));

    expect(createLayout).toHaveBeenCalledWith({ code: "U_SHAPE", name: "U-shape", description: "" });
  });

  it("needs a code and a name", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Add layout" }));

    expect(screen.getByText("Enter a short code, for example U_SHAPE.")).toBeInTheDocument();
    expect(screen.getByText("Enter the layout name.")).toBeInTheDocument();
    expect(createLayout).not.toHaveBeenCalled();
  });

  it("renames a layout", async () => {
    vi.mocked(updateLayout).mockResolvedValue({ ...theatre, name: "Theatre style" });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Edit Theatre" }));
    const name = screen.getByLabelText("Name", { selector: "#layout-name-2" });
    await userEvent.clear(name);
    await userEvent.type(name, "Theatre style");
    await userEvent.click(screen.getByRole("button", { name: "Save layout" }));

    expect(updateLayout).toHaveBeenCalledWith(2, { name: "Theatre style", description: "" });
  });

  it("retires a layout", async () => {
    vi.mocked(updateLayout).mockResolvedValue({ ...theatre, is_active: false });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Retire" }));

    expect(updateLayout).toHaveBeenCalledWith(2, { is_active: false });
  });

  it("explains why a layout in use cannot be deleted", async () => {
    vi.mocked(deleteLayout).mockRejectedValue(
      new ApiError(409, {}, "Theatre is used by venues, events or bookings. Retire it instead of deleting it."),
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Delete Theatre" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Retire it instead");
  });
});

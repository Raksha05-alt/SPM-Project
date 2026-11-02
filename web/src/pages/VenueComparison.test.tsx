import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { compareAvailability } from "../api/availability";
import { VenueComparison } from "./VenueComparison";

vi.mock("../api/availability", () => ({ compareAvailability: vi.fn() }));

it("compares all statuses, explains no whole-period match and refreshes", async () => {
  const start = "2026-11-02T09:00:00+08:00", end = "2026-11-02T13:00:00+08:00";
  vi.mocked(compareAvailability).mockResolvedValue({ starts_at: start, ends_at: end,
    message: "No venues are available for the whole period.", venues: [
      { venue_id: 1, name: "Partial room", status: "partial", available: false,
        reasons: ["Recorded venue blocks overlap this period."], free_segments: [{ starts_at: start, ends_at: "2026-11-02T10:00:00+08:00" }] },
      { venue_id: 2, name: "Blocked room", status: "unavailable", available: false, reasons: [], free_segments: [] },
    ] });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><VenueComparison /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Comparison start"), { target: { value: "2026-11-02T09:00" } });
  fireEvent.change(screen.getByLabelText("Comparison end"), { target: { value: "2026-11-02T13:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Compare venues" }));
  expect(await screen.findByText("Partly available")).toBeInTheDocument();
  expect(screen.getByText("Unavailable for the whole period")).toBeInTheDocument();
  expect(screen.getByText("No venues are available for the whole period.")).toBeInTheDocument();
  expect(screen.getByText(/^Free:/)).toBeInTheDocument();
  expect(compareAvailability).toHaveBeenCalledWith(start, end);
  vi.mocked(compareAvailability).mockResolvedValue({ starts_at: start, ends_at: end, message: "", venues: [
    { venue_id: 1, name: "Partial room", status: "available", available: true, reasons: [], free_segments: [{ starts_at: start, ends_at: end }] },
  ] });
  fireEvent.click(screen.getByRole("button", { name: "Refresh comparison" }));
  expect(await screen.findByText("Available for the whole period")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByText("Partly available")).not.toBeInTheDocument());
});

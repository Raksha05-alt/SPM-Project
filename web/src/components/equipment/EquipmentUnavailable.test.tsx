import { ApiError } from "../../api/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { recordEquipmentUnavailable } from "../../api/confirmation";
import type { EquipmentRequest } from "../../types";
import { EquipmentUnavailable } from "./EquipmentUnavailable";

vi.mock("../../api/confirmation", () => ({ recordEquipmentUnavailable: vi.fn() }));

const ITEM = { id: 11, quantity: 3, equipment_type_name: "Microphone" } as EquipmentRequest;

function renderIt(refresh = vi.fn().mockResolvedValue(undefined)) {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <EquipmentUnavailable item={ITEM} refresh={refresh} />
    </QueryClientProvider>,
  );
  return refresh;
}

describe("EquipmentUnavailable (SCRUM-58 AC3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("needs a reason, then records it", async () => {
    vi.mocked(recordEquipmentUnavailable).mockResolvedValue({ detail: "Recorded." });
    const user = userEvent.setup();
    const refresh = renderIt();

    await user.click(screen.getByRole("button", { name: "Record as unavailable" }));
    const submit = screen.getByRole("button", { name: "Record unavailable" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText("Why is it unavailable?"), "All units out for repair.");
    await user.click(submit);

    expect(recordEquipmentUnavailable).toHaveBeenCalledWith(11, "All units out for repair.");
    expect(await screen.findByRole("status")).toHaveTextContent("Recorded.");
    expect(refresh).toHaveBeenCalled();
  });

  it("cancelling sends nothing", async () => {
    const user = userEvent.setup();
    renderIt();

    await user.click(screen.getByRole("button", { name: "Record as unavailable" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(recordEquipmentUnavailable).not.toHaveBeenCalled();
  });
});

it.each([new Error("Connection interrupted"), new ApiError(409, {}, "Refused")])(
  "US-58 retains the unavailable reason and refreshes after a failed recording (%s)",
  async (error) => {
    vi.mocked(recordEquipmentUnavailable).mockReset().mockRejectedValueOnce(error).mockResolvedValue({ detail: "Recorded after retry." });
    const refresh = renderIt();
    await userEvent.click(screen.getByRole("button", { name: "Record as unavailable" }));
    await userEvent.type(screen.getByLabelText("Why is it unavailable?"), "  Awaiting repair.  ");
    await userEvent.click(screen.getByRole("button", { name: "Record unavailable" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not record it.");
    expect(screen.getByLabelText("Why is it unavailable?")).toHaveValue("  Awaiting repair.  ");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(refresh).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Record unavailable" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Recorded after retry.");
    expect(recordEquipmentUnavailable).toHaveBeenLastCalledWith(11, "Awaiting repair.");
    expect(refresh).toHaveBeenCalledTimes(2);
  },
);

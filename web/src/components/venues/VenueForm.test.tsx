import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { fieldErrors, VenueForm } from "./VenueForm";

describe("fieldErrors", () => {
  it("takes the first message for each field of a 400 response", () => {
    const error = new ApiError(400, { capacity: ["Too small.", "Other"], name: "Taken." }, "x");

    expect(fieldErrors(error)).toEqual({ capacity: "Too small.", name: "Taken." });
  });

  it("ignores anything that is not a validation error", () => {
    expect(fieldErrors(new ApiError(403, {}, "x"))).toEqual({});
    expect(fieldErrors(new ApiError(400, null, "x"))).toEqual({});
    expect(fieldErrors(new Error("x"))).toEqual({});
  });
});

it("US-9 records selected operating days in calendar order and an out-of-service venue", async () => {
  const save = vi.fn();
  render(<QueryClientProvider client={new QueryClient()}>
    <VenueForm venue={null} saving={false} error={null} onSave={save} onCancel={vi.fn()} />
  </QueryClientProvider>);
  await userEvent.type(screen.getByLabelText("Name"), "Training room");
  await userEvent.type(screen.getByLabelText("Location"), "Level 3");
  fireEvent.change(screen.getByLabelText("Maximum capacity"), { target: { value: "20" } });
  await userEvent.click(screen.getByLabelText("Tue"));
  await userEvent.click(screen.getByLabelText("Mon"));
  await userEvent.click(screen.getByLabelText("Mon"));
  await userEvent.click(screen.getByLabelText("In service"));
  fireEvent.submit(screen.getByRole("form", { name: "Venue details" }));
  expect(save).toHaveBeenCalledWith(expect.objectContaining({
    name: "Training room", capacity: 20, operating_days: [0, 2, 3, 4, 5, 6], in_service: false,
  }));
});

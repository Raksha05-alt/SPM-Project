import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client";
import { fieldErrors } from "./VenueForm";

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

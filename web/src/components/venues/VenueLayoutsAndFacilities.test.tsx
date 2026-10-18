import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import type { Venue } from "../../types";
import { toggleFacility, VenueForm } from "./VenueForm";

const HALL: Venue = {
  id: 3,
  name: "Harbour Hall",
  location: "Level 2, Marina Wing",
  capacity: 200,
  facilities: ["Projector"],
  layouts: ["THEATRE"],
  layout_labels: ["Theatre"],
  wheelchair_access: null,
  accessibility_notes: "",
  opens_at: "08:00:00",
  closes_at: "22:00:00",
  operating_days: [0, 1, 2, 3, 4],
  operating_hours: "08:00-22:00 (Mon, Tue, Wed, Thu, Fri)",
  in_service: true,
  operational_status: "In service",
  missing_information: [],
  created_by_name: "Vera Venue",
  updated_by_name: "Vera Venue",
  created_at: "2026-10-01T01:00:00Z",
  updated_at: "2026-10-01T01:00:00Z",
};

function renderForm(error: unknown = null) {
  const onSave = vi.fn();
  render(
    <VenueForm venue={HALL} saving={false} error={error} onSave={onSave} onCancel={vi.fn()} />,
  );
  return onSave;
}

describe("SCRUM-5 venue layouts and facilities", () => {
  it("AC1: offers every layout on the agreed list, with the saved ones ticked", () => {
    renderForm();

    for (const label of ["Classroom", "Theatre", "Boardroom", "Banquet", "Exhibition"]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByLabelText("Theatre")).toBeChecked();
    expect(screen.getByLabelText("Banquet")).not.toBeChecked();
  });

  it("AC1: saves the layouts Venue Staff select", async () => {
    const onSave = renderForm();

    await userEvent.click(screen.getByLabelText("Banquet"));
    await userEvent.click(screen.getByLabelText("Classroom"));
    await userEvent.click(screen.getByLabelText("Theatre"));
    await userEvent.click(screen.getByRole("button", { name: "Save venue" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ layouts: ["BANQUET", "CLASSROOM"] }),
    );
  });

  it("AC1: shows the reason when the API refuses a layout", () => {
    renderForm(new ApiError(400, { layouts: ["Unknown layout: CABARET."] }, "Bad request"));

    expect(screen.getByText("Unknown layout: CABARET.")).toBeInTheDocument();
  });

  it("AC2: records video-conferencing and accessibility facilities in one click", async () => {
    const onSave = renderForm();

    await userEvent.click(screen.getByLabelText("Video conferencing"));
    await userEvent.click(screen.getByLabelText("Step-free access"));

    expect(screen.getByLabelText("Facilities")).toHaveValue(
      "Projector, Video conferencing, Step-free access",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save venue" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        facilities: ["Projector", "Video conferencing", "Step-free access"],
      }),
    );
  });

  it("AC2: unticking a common facility removes it, and typed facilities tick it", async () => {
    renderForm();
    const text = screen.getByLabelText("Facilities");

    await userEvent.type(text, ", hearing LOOP");
    expect(screen.getByLabelText("Hearing loop")).toBeChecked();

    await userEvent.click(screen.getByLabelText("Hearing loop"));
    expect(text).toHaveValue("Projector");
    expect(screen.getByLabelText("Hearing loop")).not.toBeChecked();
  });

  it("AC2: other facilities can still be typed freely", async () => {
    const onSave = renderForm();

    await userEvent.type(screen.getByLabelText("Facilities"), ", Stage lighting");
    await userEvent.click(screen.getByRole("button", { name: "Save venue" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ facilities: ["Projector", "Stage lighting"] }),
    );
  });
});

describe("toggleFacility", () => {
  it("adds a missing facility and removes a present one, ignoring case and spacing", () => {
    expect(toggleFacility("", "Hearing loop")).toBe("Hearing loop");
    expect(toggleFacility("Projector", "Hearing loop")).toBe("Projector, Hearing loop");
    expect(toggleFacility(" Projector ,  hearing loop ", "Hearing loop")).toBe("Projector");
  });
});

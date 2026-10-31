import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { listLayouts } from "../../api/layouts";
import { SEED_LAYOUTS } from "../../api/__mocks__/layouts";
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

function renderForm(error: unknown = null, venue: Venue = HALL) {
  const onSave = vi.fn();
  // SCRUM-91 - layouts are read from the catalogue through React Query.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <VenueForm venue={venue} saving={false} error={error} onSave={onSave} onCancel={vi.fn()} />
    </QueryClientProvider>,
  );
  return onSave;
}

beforeEach(() => {
  vi.mocked(listLayouts).mockResolvedValue(SEED_LAYOUTS);
});

describe("SCRUM-5 venue layouts and facilities", () => {
  it("AC1: offers every layout on the agreed list, with the saved ones ticked", async () => {
    renderForm();

    for (const label of ["Classroom", "Theatre", "Boardroom", "Banquet", "Exhibition"]) {
      expect(await screen.findByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.getByLabelText("Theatre")).toBeChecked();
    expect(screen.getByLabelText("Banquet")).not.toBeChecked();
  });

  it("AC1: saves the layouts Venue Staff select", async () => {
    const onSave = renderForm();

    await userEvent.click(await screen.findByLabelText("Banquet"));
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

describe("SCRUM-91 venue form uses the layout catalogue", () => {
  it("AC1/AC2: offers new layouts and shows each layout's current name", async () => {
    vi.mocked(listLayouts).mockResolvedValue([
      { ...SEED_LAYOUTS[1], name: "Lecture theatre" },
      { ...SEED_LAYOUTS[0], code: "CABARET", name: "Cabaret", sort_order: 6 },
    ]);

    renderForm();

    expect(await screen.findByLabelText("Lecture theatre")).toBeChecked();
    expect(screen.getByLabelText("Cabaret")).not.toBeChecked();
    expect(screen.queryByLabelText("Theatre")).not.toBeInTheDocument();
  });

  it("AC4: hides retired layouts, except one the venue already supports", async () => {
    vi.mocked(listLayouts).mockResolvedValue([
      { ...SEED_LAYOUTS[1], is_active: false },
      { ...SEED_LAYOUTS[3], is_active: false },
      SEED_LAYOUTS[0],
    ]);

    renderForm();

    const theatre = await screen.findByLabelText(/Theatre/);
    expect(theatre).toBeChecked();
    expect(theatre.closest("label")).toHaveTextContent("Theatre(retired)");
    expect(screen.queryByLabelText(/Banquet/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Classroom")).toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { updateEvent } from "../../api/planning";
import { EventEditPanel } from "./EventEditPanel";
import { planningEvent } from "./fixtures";

vi.mock("../../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/planning")>()),
  updateEvent: vi.fn(),
}));

function renderPanel(event = planningEvent()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EventEditPanel event={event} />
    </QueryClientProvider>,
  );
}

describe("SCRUM-61 edit event details during planning", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: saves only the changed fields; an ordinary edit shows no warning", async () => {
    vi.mocked(updateEvent).mockResolvedValue({
      ...planningEvent({ purpose: "Partner briefing 2026" }),
      significant_change: { significant: false, changed_fields: [], affected_arrangements: [] },
    });

    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Edit event details" }));
    const purpose = screen.getByLabelText("Purpose");
    await userEvent.clear(purpose);
    await userEvent.type(purpose, "Partner briefing 2026");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(updateEvent).toHaveBeenCalledWith(9, { purpose: "Partner briefing 2026" });
    expect(await screen.findByText("Changes saved.")).toBeInTheDocument();
    expect(screen.queryByText(/Significant change/)).not.toBeInTheDocument();
  });

  it("AC4: invalid values are blocked before sending", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Edit event details" }));
    const attendance = screen.getByLabelText("Expected attendance");
    await userEvent.clear(attendance);
    await userEvent.type(attendance, "0");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      screen.getByText("Expected attendance must be at least one person."),
    ).toBeInTheDocument();
    expect(updateEvent).not.toHaveBeenCalled();
  });

  it("AC4: shows the API's field errors", async () => {
    vi.mocked(updateEvent).mockRejectedValue(
      new ApiError(400, { preferred_start: ["The preferred start date cannot be in the past."] }, "Something went wrong."),
    );

    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Edit event details" }));
    await userEvent.type(screen.getByLabelText("Event name"), " 2026");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("The preferred start date cannot be in the past."),
    ).toBeInTheDocument();
  });

  it("AC2/AC3: shows the API's refusal for a coordinator who may not edit", async () => {
    vi.mocked(updateEvent).mockRejectedValue(
      new ApiError(403, { detail: "You do not have access to this event request." }, "You do not have access to this event request."),
    );

    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Edit event details" }));
    await userEvent.type(screen.getByLabelText("Event name"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have access to this event request.",
    );
  });
});

describe("SCRUM-59 significant change warning", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: lists the arrangements a significant change affects", async () => {
    vi.mocked(updateEvent).mockResolvedValue({
      ...planningEvent({ expected_attendance: 400 }),
      significant_change: {
        significant: true,
        changed_fields: ["expected attendance"],
        affected_arrangements: ["Venue booking for Hall A", "2 x Projector"],
      },
    });

    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Edit event details" }));
    const attendance = screen.getByLabelText("Expected attendance");
    await userEvent.clear(attendance);
    await userEvent.type(attendance, "400");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(updateEvent).toHaveBeenCalledWith(9, { expected_attendance: 400 });
    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("Significant change: expected attendance.");
    expect(warning).toHaveTextContent("Venue booking for Hall A");
    expect(warning).toHaveTextContent("2 x Projector");
  });
});

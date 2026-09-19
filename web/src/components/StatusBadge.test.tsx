import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("US-06.1 AC1: shows the human readable status label", () => {
    render(<StatusBadge status="SUBMITTED" label="Submitted" />);

    expect(screen.getByText("Submitted")).toBeInTheDocument();
  });

  it("US-06.1 AC2: carries the plain language explanation as a tooltip", () => {
    render(
      <StatusBadge
        status="DRAFT"
        label="Draft"
        title="Still being written by the client."
      />,
    );

    expect(screen.getByText("Draft")).toHaveAttribute(
      "title",
      "Still being written by the client.",
    );
  });

  it("gives each status its own tone so the queue is scannable", () => {
    const { rerender } = render(<StatusBadge status="DRAFT" label="Draft" />);
    const draftClass = screen.getByText("Draft").className;

    rerender(<StatusBadge status="CONFIRMED" label="Confirmed" />);

    expect(screen.getByText("Confirmed").className).not.toEqual(draftClass);
  });
});

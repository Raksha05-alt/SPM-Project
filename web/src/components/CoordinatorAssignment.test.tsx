import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CoordinatorAssignment } from "./CoordinatorAssignment";

describe("SCRUM-51 coordinator details", () => {
  it("AC4: shows the assigned coordinator and email contact", () => {
    render(<CoordinatorAssignment event={{ coordinator_name: "Cora Coordinator", coordinator_email: "cora@example.com", assignment_requires_attention: false }} />);
    expect(screen.getByText("Cora Coordinator")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "cora@example.com" })).toHaveAttribute("href", "mailto:cora@example.com");
  });

  it("AC5: explains that an unassigned request remains submitted", () => {
    render(<CoordinatorAssignment event={{ coordinator_name: null, coordinator_email: null, assignment_requires_attention: true }} />);
    expect(screen.getByText(/Your request is submitted and needs ConnectSphere staff/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("does not label legacy unassigned requests as failed assignments", () => {
    render(<CoordinatorAssignment event={{ coordinator_name: null, coordinator_email: null, assignment_requires_attention: false }} />);
    expect(screen.getByText("A coordinator has not been assigned yet.")).toBeInTheDocument();
  });
});

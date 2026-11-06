import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { Clarification } from "../types";
import { ClarificationHistory, OpenClarification } from "./Clarifications";

const question: Clarification = {
  id: 3, message: "Please confirm the access needs.", fields: [],
  requested_by_name: null, requested_at: "2030-06-18T01:00:00Z", resolved_at: null, comments: [],
};

it("US-49 shows an unanswered question without inventing a coordinator name or requested fields", () => {
  render(<><OpenClarification clarification={question} /><ClarificationHistory clarifications={[question]} /></>);
  expect(screen.getByRole("alert")).toHaveTextContent("Your coordinator needs more information:");
  expect(screen.queryByText(/Please check:/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Items:/)).not.toBeInTheDocument();
  expect(screen.getByText(/Asked by a coordinator/)).toHaveTextContent("awaiting answer");
  expect(screen.queryByRole("list", { name: "Clarification notes" })).not.toBeInTheDocument();
});

it("US-49/92 retains answered questions and offline notes when author details are unavailable", () => {
  render(<ClarificationHistory clarifications={[{
    ...question, fields: ["accessibility_needs", "custom_requirement"], resolved_at: "2030-06-18T02:00:00Z",
    comments: [{ id: 8, body: "Hearing loop confirmed by telephone.", author_name: null, author_role: null, created_at: "2030-06-18T01:30:00Z" }],
  }]} />);
  expect(screen.getByText("Items: Accessibility needs, custom_requirement")).toBeVisible();
  expect(screen.getByText(/Asked by a coordinator/)).toHaveTextContent("answered");
  expect(screen.getByRole("list", { name: "Clarification notes" })).toHaveTextContent("Hearing loop confirmed by telephone.");
  expect(screen.getByText(/Unknown/)).not.toHaveTextContent("null");
});

it("US-49 omits the history section when no question has been asked", () => {
  render(<ClarificationHistory clarifications={[]} />);
  expect(screen.queryByRole("region", { name: "Clarification history" })).not.toBeInTheDocument();
});

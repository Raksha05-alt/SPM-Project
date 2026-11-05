import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { updateMe } from "../api/auth";
import { ApiError } from "../api/client";
import { AuthContext, type AuthState } from "../auth/AuthContext";
import type { User } from "../types";
import { AccountPage } from "./AccountPage";

vi.mock("../api/auth", () => ({ updateMe: vi.fn() }));

const ADA: User = {
  id: 3,
  email: "organiser@acme.example",
  first_name: "Ada",
  last_name: "Organiser",
  role: "ORGANISER",
  role_label: "Event Organiser",
  organisation: 1,
  organisation_name: "Acme Pte Ltd",
  landing_path: "/organiser",
};

function renderPage(user: User | null = ADA) {
  const updateUser = vi.fn();
  const value: AuthState = { user, loading: false, signIn: vi.fn(), signOut: vi.fn(), updateUser };
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
      <AuthContext.Provider value={value}>
        <AccountPage />
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return { updateUser };
}

async function replace(label: string | RegExp, value: string) {
  const input = screen.getByLabelText(label);
  await userEvent.clear(input);
  if (value) await userEvent.type(input, value);
}

describe("SCRUM-2 account page", () => {
  beforeEach(() => vi.mocked(updateMe).mockReset());

  it("AC1: shows my name, role, organisation and email", () => {
    renderPage();

    const account = screen.getByRole("region", { name: "Account" });
    expect(within(account).getByText("Ada Organiser")).toBeInTheDocument();
    expect(within(account).getByText("Event Organiser")).toBeInTheDocument();
    expect(within(account).getByText("Acme Pte Ltd")).toBeInTheDocument();
    expect(within(account).getByText("organiser@acme.example")).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toHaveValue("organiser@acme.example");
  });

  it("AC1: staff without a client organisation see ConnectSphere", () => {
    renderPage({ ...ADA, organisation: null, organisation_name: null, role: "COORDINATOR", role_label: "Event Coordinator" });

    expect(within(screen.getByRole("region", { name: "Account" })).getByText("ConnectSphere")).toBeInTheDocument();
  });

  it("AC3: offers no way to change role or organisation", () => {
    renderPage();

    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/organisation/i)).not.toBeInTheDocument();
    expect(screen.getByText(/cannot be changed here/)).toBeInTheDocument();
  });

  it("AC2: sends only the changed fields, updates the header and says so", async () => {
    const saved = { ...ADA, first_name: "Adaline" };
    vi.mocked(updateMe).mockResolvedValue({ ...saved, changed_fields: ["first_name"] });
    const { updateUser } = renderPage();

    await replace("First name", "Adaline");
    await userEvent.click(screen.getByRole("button", { name: "Save details" }));

    expect(updateMe).toHaveBeenCalledWith({ first_name: "Adaline" });
    expect(await screen.findByRole("status")).toHaveTextContent("Your details were saved.");
    expect(updateUser).toHaveBeenCalledWith(saved);
  });

  it("AC2: a new email reminds me how I sign in next time", async () => {
    vi.mocked(updateMe).mockResolvedValue({
      ...ADA,
      email: "ada@acme.example",
      changed_fields: ["email"],
    });
    renderPage();

    await replace("Email address", "ada@acme.example");
    await userEvent.click(screen.getByRole("button", { name: "Save details" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Sign in with your new email address next time.",
    );
    expect(screen.getByLabelText("Email address")).toHaveValue("ada@acme.example");
  });

  it("says when there was nothing to save", async () => {
    vi.mocked(updateMe).mockResolvedValue({ ...ADA, changed_fields: [] });
    renderPage();

    await userEvent.click(screen.getByRole("button", { name: "Save details" }));

    expect(updateMe).toHaveBeenCalledWith({});
    expect(await screen.findByRole("status")).toHaveTextContent("Nothing to save");
  });

  it("AC4: names each missing or invalid field next to it", async () => {
    vi.mocked(updateMe).mockRejectedValueOnce(
      new ApiError(
        400,
        {
          detail: "Some details are missing or invalid.",
          missing_fields: ["email"],
          email: ["Email address is required."],
          first_name: ["First name is required."],
        },
        "Some details are missing or invalid.",
      ),
    );
    renderPage();

    await replace("Email address", "");
    await replace("First name", "");
    await userEvent.click(screen.getByRole("button", { name: "Save details" }));

    expect(await screen.findByText("Email address is required.")).toBeInTheDocument();
    expect(screen.getByText("First name is required.")).toBeInTheDocument();
    expect(screen.getByText("Some details are missing or invalid.")).toBeInTheDocument();
  });

  it("AC3: shows the API's refusal", async () => {
    vi.mocked(updateMe).mockRejectedValueOnce(
      new ApiError(403, { refused_fields: ["role"] }, "You can only change your own name and email address here."),
    );
    renderPage();

    await userEvent.click(screen.getByRole("button", { name: "Save details" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("You can only change your own name");
  });

  it("shows a body-level problem and a network failure", async () => {
    vi.mocked(updateMe)
      .mockRejectedValueOnce(new ApiError(400, { non_field_errors: ["Send the details to change."] }, "x"))
      .mockRejectedValueOnce(new Error("offline"));
    renderPage();

    await userEvent.click(screen.getByRole("button", { name: "Save details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Send the details to change.");

    await userEvent.type(screen.getByLabelText("Last name (optional)"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not save your details.");
  });

  it("renders nothing without a signed-in user", () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthContext.Provider value={{ user: null, loading: false, signIn: vi.fn(), signOut: vi.fn(), updateUser: vi.fn() }}>
          <AccountPage />
        </AuthContext.Provider>
      </QueryClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

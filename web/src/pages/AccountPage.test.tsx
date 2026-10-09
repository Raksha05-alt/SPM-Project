import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getAccount, updateAccount, type Account } from "../api/account";
import { ApiError } from "../api/client";
import { AccountPage } from "./AccountPage";

vi.mock("../api/account", () => ({ getAccount: vi.fn(), updateAccount: vi.fn() }));

function account(overrides: Partial<Account> = {}): Account {
  return {
    id: 1,
    email: "ada@acme.example",
    phone: "6123 4567",
    first_name: "Ada",
    last_name: "Organiser",
    role: "ORGANISER",
    role_label: "Event Organiser",
    organisation: 3,
    organisation_name: "Acme Pte Ltd",
    landing_path: "/organiser",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountPage />
    </QueryClientProvider>,
  );
}

describe("SCRUM-2 maintain my account", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: shows my details, with role and organisation read-only", async () => {
    vi.mocked(getAccount).mockResolvedValue(account());
    renderPage();
    expect(await screen.findByLabelText("First name")).toHaveValue("Ada");
    expect(screen.getByLabelText("Last name")).toHaveValue("Organiser");
    expect(screen.getByLabelText("Email")).toHaveValue("ada@acme.example");
    expect(screen.getByLabelText("Phone")).toHaveValue("6123 4567");
    expect(screen.getByText("Event Organiser")).toBeInTheDocument();
    expect(screen.getByText("Acme Pte Ltd")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Role|Organisation/)).not.toBeInTheDocument();
  });

  it("AC2: saves first name, last name, email and phone and confirms", async () => {
    vi.mocked(getAccount).mockResolvedValue(account());
    vi.mocked(updateAccount).mockResolvedValue(account({ phone: "6999 0000" }));
    renderPage();
    const phone = await screen.findByLabelText("Phone");
    await userEvent.clear(phone);
    await userEvent.type(phone, "6999 0000");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(updateAccount).toHaveBeenCalledWith({
      first_name: "Ada",
      last_name: "Organiser",
      email: "ada@acme.example",
      phone: "6999 0000",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Your details have been saved.");
  });

  it("AC4: shows field errors from the API", async () => {
    vi.mocked(getAccount).mockResolvedValue(account());
    vi.mocked(updateAccount).mockRejectedValue(
      new ApiError(
        400,
        { email: ["Another account already uses this email address."], first_name: ["This field may not be blank."] },
        "Something went wrong.",
      ),
    );
    renderPage();
    await screen.findByLabelText("Email");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText("Another account already uses this email address."),
    ).toBeInTheDocument();
    expect(screen.getByText("This field may not be blank.")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("AC3: shows the refusal when the API will not save", async () => {
    vi.mocked(getAccount).mockResolvedValue(account());
    vi.mocked(updateAccount).mockRejectedValue(
      new ApiError(403, { detail: "You cannot change your own role or organisation." }, "You cannot change your own role or organisation."),
    );
    renderPage();
    await screen.findByLabelText("Email");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You cannot change your own role or organisation.",
    );
  });
});

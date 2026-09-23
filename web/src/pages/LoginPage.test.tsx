import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthContext } from "../auth/AuthContext";
import { LoginPage } from "./LoginPage";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

function renderLogin(signIn: ReturnType<typeof vi.fn>) {
  return render(
    <AuthContext.Provider value={{ user: null, loading: false, signIn, signOut: vi.fn() }}>
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("LoginPage", () => {
  it("US-01.1 AC1: sends the user to the landing path the API chose", async () => {
    const signIn = vi.fn().mockResolvedValue({ landing_path: "/coordinator" });
    renderLogin(signIn);

    await userEvent.type(screen.getByLabelText("Email"), "coordinator@connectsphere.example");
    await userEvent.type(screen.getByLabelText("Password"), "hunter2");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/coordinator", { replace: true }),
    );
  });

  it("US-01.1 AC3: refuses without saying which field was wrong", async () => {
    const signIn = vi.fn().mockRejectedValue(new Error("401"));
    renderLogin(signIn);

    await userEvent.type(screen.getByLabelText("Email"), "someone@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Those sign-in details were not recognised.");
    expect(alert.textContent?.toLowerCase()).not.toContain("password is");
    expect(alert.textContent?.toLowerCase()).not.toContain("no such user");
  });
});

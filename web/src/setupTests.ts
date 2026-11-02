import "@testing-library/jest-dom/vitest";

// SCRUM-91 - every form reads the room layout catalogue. Tests get the seeded
// five layouts by default (src/api/__mocks__/layouts.ts); a test can still
// override listLayouts or import the real module with vi.importActual.
import { vi } from "vitest";
vi.mock("./api/layouts");

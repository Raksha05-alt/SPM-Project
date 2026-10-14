import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Week 7 clarification - many forms list room layouts from the catalogue. Unless a
// test says otherwise, the catalogue holds the five starter layouts.
vi.mock("./api/layouts", () => ({
  listLayouts: vi.fn().mockResolvedValue([
    { id: 1, code: "CLASSROOM", name: "Classroom", description: "", is_active: true },
    { id: 2, code: "THEATRE", name: "Theatre", description: "", is_active: true },
    { id: 3, code: "BOARDROOM", name: "Boardroom", description: "", is_active: true },
    { id: 4, code: "BANQUET", name: "Banquet", description: "", is_active: true },
    { id: 5, code: "EXHIBITION", name: "Exhibition", description: "", is_active: true },
  ]),
  createLayout: vi.fn(),
  updateLayout: vi.fn(),
  deleteLayout: vi.fn(),
}));

import { expect, it, vi } from "vitest";
import { request } from "./client";
import { getVenueReviews } from "./venueReviews";

vi.mock("./client", () => ({ request: vi.fn() }));

it("reads the SCRUM-66 venue reviews", () => {
  getVenueReviews(4);
  expect(request).toHaveBeenCalledWith("/api/events/4/venue-reviews/");
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "./client";
import {
  addVenueToShortlist,
  getVenueShortlist,
  removeVenueFromShortlist,
  searchVenues,
} from "./venueDiscovery";

vi.mock("./client", () => ({ request: vi.fn() }));

describe("venue discovery API contract", () => {
  beforeEach(() => vi.clearAllMocks());

  it("encodes all supplied filters and repeats required facilities", () => {
    searchVenues({
      attendance: 60,
      layout: "THEATRE",
      facilities: ["Hearing loop", "A&B"],
      start: "2027-03-01T01:00:00Z",
      end: "2027-03-01T09:00:00Z",
    });
    const path = vi.mocked(request).mock.calls[0][0];
    const params = new URL(path, "http://localhost").searchParams;
    expect(params.getAll("facilities")).toEqual(["Hearing loop", "A&B"]);
    expect(params.get("attendance")).toBe("60");
    expect(params.get("start")).toBe("2027-03-01T01:00:00Z");
    expect(params.get("layout")).toBe("THEATRE");
  });

  it("omits empty optional filters", () => {
    searchVenues({ attendance: undefined, layout: "", facilities: [] });
    expect(request).toHaveBeenCalledWith("/api/venues/search/?");
  });

  it("scopes reads, additions and removals to the event and venue", () => {
    getVenueShortlist(9);
    addVenueToShortlist(9, 3, { attendance: 60 });
    removeVenueFromShortlist(9, 3);
    expect(request).toHaveBeenNthCalledWith(1, "/api/events/9/venue-shortlist/");
    expect(request).toHaveBeenNthCalledWith(2, "/api/events/9/venue-shortlist/", {
      method: "POST",
      body: { venue_id: 3, criteria: { attendance: 60 } },
    });
    expect(request).toHaveBeenNthCalledWith(3, "/api/events/9/venue-shortlist/3/", {
      method: "DELETE",
    });
  });
});

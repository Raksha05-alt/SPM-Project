import { createVenue, getVenue, listVenuesSupportingLayout, updateVenue } from "./venues";
import type { VenueInput } from "./venues";
import { approveRevisedEquipment } from "./equipmentPlans";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError } from "./client";
import { compareAvailability, findAvailableVenues, getAvailability, getBlockHistory, getBlocks, removeBlock, saveBlock } from "./availability";
import { getEquipmentAvailability, getEquipmentHolders, listEquipmentTypes, listEventEquipment, requestEquipment } from "./equipment";
import { getEventSuitability } from "./suitability";
import { addClarificationNote, approveEvent, rejectEvent, requestClarification, resumeReview, updateEvent } from "./events";
import { decideSafetyCheck, getSafetyCheck, listSafetyChecks, requestSafetyCheck } from "./safety";
import { confirmEvent, getConfirmedArrangements, recordEquipmentUnavailable } from "./confirmation";
import { approveBooking, confirmVenueHold, updateHoldExpiry } from "./venueBookings";

// Test the real domain clients together with the shared HTTP adapter.
// The HTTP responses below are contract fixtures, not backend business logic.
function server(...responses: { status?: number; body?: unknown }[]) {
  document.cookie = "csrftoken=wire-token; path=/";
  const fetch = vi.fn();
  for (const { status = 200, body } of responses) {
    fetch.mockResolvedValueOnce(new Response(
      status === 204 || body === undefined ? null : JSON.stringify(body), { status },
    ));
  }
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function outgoing(fetch: ReturnType<typeof server>, index: number) {
  const [path, init] = fetch.mock.calls[index] as [string, RequestInit];
  expect(init.credentials).toBe("same-origin");
  if (init.method !== "GET") {
    expect(init.headers).toMatchObject({ "X-CSRFToken": "wire-token" });
  }
  return {
    url: new URL(path, "https://connectsphere.example"),
    method: init.method,
    body: init.body ? JSON.parse(String(init.body)) as unknown : undefined,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "csrftoken=; Max-Age=0; path=/";
});

it("US-62/63/71 keeps timezone offsets and repeated facility filters intact across venue searches", async () => {
  const period = { starts_at: "2030-06-18T09:00:00+08:00", ends_at: "2030-06-18T11:00:00+08:00" };
  const fetch = server(
    { body: { event: 42, venues: [{ id: 3, suitable: false, reasons: ["Missing hearing loop"] }] } },
    { body: { event: 42, venues: [] } },
    { body: { ...period, venues: [{ venue_id: 3, status: "partial", reasons: ["Blocked for maintenance"] }] } },
    { body: [{ id: 4, name: "Free room" }] },
    { body: { ...period, venue_id: 3, available: false, blocks: [{ reason: "Maintenance" }] } },
  );
  expect((await getEventSuitability(42, ["Projector & screen", "Hearing loop"], true)).venues[0].reasons).toEqual(["Missing hearing loop"]);
  await getEventSuitability(42);
  const comparison = await compareAvailability(period.starts_at, period.ends_at);
  expect(comparison.venues[0].status).toBe("partial");
  expect((await findAvailableVenues(period.starts_at, period.ends_at))[0].name).toBe("Free room");
  expect((await getAvailability(3, period.starts_at, period.ends_at)).available).toBe(false);
  const filters = outgoing(fetch, 0).url.searchParams;
  expect(filters.getAll("facilities")).toEqual(["Projector & screen", "Hearing loop"]);
  expect(filters.get("wheelchair")).toBe("true");
  expect(outgoing(fetch, 1).url.search).toBe("");
  for (const index of [2, 3, 4]) {
    expect(Object.fromEntries(outgoing(fetch, index).url.searchParams)).toEqual(period);
  }
});

it("US-10/64 sends block reasons on create and update and handles a bodyless deletion", async () => {
  const input = { reason: "Maintenance & access works", reason_category: "MAINTENANCE",
    starts_at: "2030-06-18T01:00:00Z", ends_at: "2030-06-18T03:00:00Z" };
  const fetch = server(
    { body: [] }, { status: 201, body: { ...input, id: 8 } },
    { body: { ...input, id: 8, reason: "Access restored early" } },
    { body: [{ ...input, id: 1, block_id: 8, action: "UPDATED", actor_name: "Venue Staff" }] },
    { status: 204 },
  );
  expect(await getBlocks(3)).toEqual([]);
  expect((await saveBlock(3, input)).id).toBe(8);
  expect((await saveBlock(3, { ...input, reason: "Access restored early" }, 8)).reason).toBe("Access restored early");
  expect((await getBlockHistory(3))[0].actor_name).toBe("Venue Staff");
  await expect(removeBlock(3, 8)).resolves.toBeUndefined();
  expect(outgoing(fetch, 1)).toMatchObject({ method: "POST", body: input });
  expect(outgoing(fetch, 1).url.pathname).toBe("/api/venues/3/blocks/");
  expect(outgoing(fetch, 2)).toMatchObject({ method: "PATCH", body: { ...input, reason: "Access restored early" } });
  expect(outgoing(fetch, 2).url.pathname).toBe("/api/venues/3/blocks/8/");
  expect(outgoing(fetch, 4).method).toBe("DELETE");
});

it("US-12/74/76 uses one chosen period for equipment totals and holders and preserves request refusal details", async () => {
  const period = { starts_at: "2030-06-18T09:00:00+08:00", ends_at: "2030-06-18T11:00:00+08:00" };
  const input = { equipment_type: 3, quantity: 4, technical_requirements: "Wireless microphones" };
  const fetch = server(
    { body: [{ id: 3, name: "Microphone" }] }, { body: [] },
    { status: 400, body: { quantity: ["At most three can be requested."], detail: "Quantity is not valid." } },
    { status: 201, body: { detail: "Equipment requested.", request: { id: 8, ...input, quantity: 3 } } },
    { body: { event: { id: 42 }, period, equipment: [], shortfalls: [] } },
    { body: { event: { id: 42 }, period, equipment: [{ equipment_type: 3, available_quantity: 0 }], shortfalls: [] } },
    { body: { period, availability: { equipment_type: 3, available_quantity: 0 }, holders: [{ reservation: 5, quantity: 3, event: { id: 41 } }] } },
  );
  expect((await listEquipmentTypes())[0].name).toBe("Microphone");
  expect(await listEventEquipment(42)).toEqual([]);
  await expect(requestEquipment(42, input)).rejects.toMatchObject({
    status: 400, body: { quantity: ["At most three can be requested."] },
  });
  expect((await requestEquipment(42, { ...input, quantity: 3 })).request.quantity).toBe(3);
  await getEquipmentAvailability(42);
  await getEquipmentAvailability(42, period);
  await getEquipmentHolders(42, 3, period);
  expect(outgoing(fetch, 2).body).toEqual(input);
  expect(outgoing(fetch, 3).body).toEqual({ ...input, quantity: 3 });
  expect(outgoing(fetch, 4).url.search).toBe("");
  expect(Object.fromEntries(outgoing(fetch, 5).url.searchParams)).toEqual(period);
  expect(Object.fromEntries(outgoing(fetch, 6).url.searchParams)).toEqual(period);
});

it("US-49/50/52/61/92 preserves clarification selections, offline notes and decision reasons over HTTP", async () => {
  const fetch = server(
    { body: { id: 42, status: "UNDER_REVIEW" } },
    { body: { id: 42, clarifications: [{ comments: [{ body: "Client confirmed 80 attendees." }] }] } },
    { body: { id: 42, status: "SUBMITTED" } },
    { body: { id: 42, expected_attendance: 80 } },
    { body: { id: 42, status: "APPROVED" } },
    { status: 409, body: { detail: "The event has already been decided." } },
  );
  expect((await requestClarification(42, "Confirm the headcount.", ["expected_attendance"])).status).toBe("UNDER_REVIEW");
  const noted = await addClarificationNote(42, "Client confirmed 80 attendees.");
  expect(noted.clarifications[0].comments[0].body).toBe("Client confirmed 80 attendees.");
  expect((await resumeReview(42)).status).toBe("SUBMITTED");
  expect((await updateEvent(42, { expected_attendance: 80 })).expected_attendance).toBe(80);
  expect((await approveEvent(42)).status).toBe("APPROVED");
  await expect(rejectEvent(42, "Venue unavailable")).rejects.toMatchObject({ status: 409, message: "The event has already been decided." });
  expect(outgoing(fetch, 0).body).toEqual({ message: "Confirm the headcount.", fields: ["expected_attendance"] });
  expect(outgoing(fetch, 1).body).toEqual({ body: "Client confirmed 80 attendees." });
  expect(outgoing(fetch, 2).method).toBe("POST");
  expect(outgoing(fetch, 3)).toMatchObject({ method: "PATCH", body: { expected_attendance: 80 } });
  expect(outgoing(fetch, 5).body).toEqual({ reason: "Venue unavailable" });
});

it("US-58/90 keeps safety comments, unmet arrangements and server confirmation refusal visible to callers", async () => {
  const fetch = server(
    { body: [] }, { body: [{ id: 6, status: "PENDING" }] },
    { body: { id: 6, status: "PENDING" } }, { status: 201, body: { id: 6, status: "PENDING" } },
    { body: { id: 6, status: "CHANGES_REQUESTED", comment: "Clear the emergency exit." } },
    { body: { detail: "Recorded." } },
    { status: 409, body: { detail: "Safety approval is required.", missing: ["Safety"] } },
    { body: { event: 42, venues: [{ venue: "Main Hall", layout: "Theatre" }], equipment: [] } },
  );
  expect(await listSafetyChecks()).toEqual([]);
  expect((await listSafetyChecks(["PENDING", "CHANGES_REQUESTED"]))).toHaveLength(1);
  expect((await getSafetyCheck(6)).status).toBe("PENDING");
  await requestSafetyCheck(42, "Please inspect the access routes.");
  await decideSafetyCheck(6, "CHANGES_REQUESTED", "Clear the emergency exit.");
  await recordEquipmentUnavailable(8, "No accessible replacement available.");
  await expect(confirmEvent(42)).rejects.toMatchObject({ status: 409, body: { missing: ["Safety"] } });
  expect((await getConfirmedArrangements(42)).venues[0].venue).toBe("Main Hall");
  expect(outgoing(fetch, 1).url.searchParams.get("status")).toBe("PENDING,CHANGES_REQUESTED");
  expect(outgoing(fetch, 3).body).toEqual({ note: "Please inspect the access routes." });
  expect(outgoing(fetch, 4).body).toEqual({ decision: "CHANGES_REQUESTED", comment: "Clear the emergency exit." });
  expect(outgoing(fetch, 5).body).toEqual({ reason: "No accessible replacement available." });
  expect(outgoing(fetch, 6).body).toEqual({});
});

it("US-88 preserves offset deadlines, surfaces a stale hold conflict and sends confirmation without a client-selected status", async () => {
  const deadline = "2030-06-17T15:30:00+08:00";
  const fetch = server(
    { body: { detail: "Held.", booking: { id: 8, status: "HELD" } } },
    { status: 409, body: { detail: "This hold has expired." } },
    { body: { detail: "Confirmed.", booking: { id: 9, status: "APPROVED" } } },
  );
  expect((await approveBooking(8, deadline)).booking.status).toBe("HELD");
  await expect(updateHoldExpiry(8, deadline)).rejects.toMatchObject({ status: 409, message: "This hold has expired." });
  expect((await confirmVenueHold(9)).booking.status).toBe("APPROVED");
  expect(outgoing(fetch, 0).body).toEqual({ hold_until: deadline });
  expect(outgoing(fetch, 1).body).toEqual({ hold_until: deadline });
  expect(outgoing(fetch, 2).body).toEqual({});
});

it("US-6 handles an empty server error without inventing missing fields or a successful result", async () => {
  const fetch = server({ status: 503 });
  await expect(getSafetyCheck(6)).rejects.toSatisfy((error: unknown) =>
    error instanceof ApiError && error.status === 503 && error.body === null &&
    error.message === "Something went wrong." && error.missingFields.length === 0);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("US-5/9 preserves venue layout-removal confirmation and field errors through the real HTTP client", async () => {
  const fetch = server(
    { body: [{ id: 3, name: "Hall", layouts: ["THEATRE"] }] },
    { body: { id: 3, name: "Hall", layouts: ["THEATRE"] } },
    { status: 400, body: { capacity: ["Capacity must be positive."] } },
    { status: 409, body: { detail: "Approved bookings use this layout.", affected_bookings: [{ booking: 8, layout: "THEATRE" }] } },
    { body: { id: 3, name: "Hall", layouts: [] } },
  );
  expect((await listVenuesSupportingLayout("THEATRE & CABARET"))[0].name).toBe("Hall");
  expect(outgoing(fetch, 0).url.searchParams.get("layout")).toBe("THEATRE & CABARET");
  const venue = await getVenue(3);
  await expect(createVenue({ name: "Bad hall", capacity: 0 } as VenueInput)).rejects.toMatchObject({
    status: 400, body: { capacity: ["Capacity must be positive."] },
  });
  await expect(updateVenue(venue.id, { layouts: [] })).rejects.toMatchObject({
    status: 409, body: { affected_bookings: [{ booking: 8, layout: "THEATRE" }] },
  });
  expect((await updateVenue(venue.id, { layouts: [], confirm_layout_removal: true })).layouts).toEqual([]);
  expect(outgoing(fetch, 3).body).not.toHaveProperty("confirm_layout_removal");
  expect(outgoing(fetch, 4)).toMatchObject({ method: "PATCH", body: { layouts: [], confirm_layout_removal: true } });
});

it("US-75/80 refuses a stale revised-equipment approval without losing the server's revision message", async () => {
  const fetch = server(
    { status: 409, body: { detail: "Equipment changed again. Refresh before approving.", current_revision: 8 } },
    { body: { revision: 8, technical_approval: { revision: 8 } } },
  );
  await expect(approveRevisedEquipment(42, 7)).rejects.toMatchObject({ status: 409, body: { current_revision: 8 } });
  expect((await approveRevisedEquipment(42, 8)).technical_approval?.revision).toBe(8);
  expect(outgoing(fetch, 0).body).toEqual({ expected_revision: 7 });
  expect(outgoing(fetch, 1).body).toEqual({ expected_revision: 8 });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { cancelEvent, getCancellationPreview, type CancellationPreview } from "../api/cancellation";
import type { EventRequest } from "../types";
import { EventCancellation } from "./EventCancellation";
vi.mock("../api/cancellation",()=>({cancelEvent:vi.fn(),getCancellationPreview:vi.fn()}));
const EVENT={id:9,name:"Partner Summit",status:"PLANNING",preferred_end:"2027-03-01T04:00:00Z"} as EventRequest;
const SUMMARY:CancellationPreview={event:9,event_name:"Partner Summit",version:"v1",venue_bookings:[{id:4,venue__name:"Harbour Hall",status:"APPROVED",starts_at:"2027-03-01T02:00:00Z",ends_at:"2027-03-01T04:00:00Z"}],equipment_reservations:[{id:8,request__equipment_type__name:"Projector",quantity:3,starts_at:"2027-03-01T02:00:00Z",ends_at:"2027-03-01T04:00:00Z"}]};
function setup(event=EVENT){
 const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
 const invalidate=vi.spyOn(client,"invalidateQueries");
 render(<QueryClientProvider client={client}><EventCancellation event={event}/></QueryClientProvider>);
 return {user:userEvent.setup(),client,invalidate};
}
async function open(user:ReturnType<typeof userEvent.setup>){
 await user.click(screen.getByRole("button",{name:"Cancel event"}));await screen.findByText("Harbour Hall: APPROVED");
}
async function consent(user:ReturnType<typeof userEvent.setup>){
 await user.type(screen.getByLabelText("Cancellation reason"),"  Client cancelled  ");await user.click(screen.getByRole("checkbox"));
}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(getCancellationPreview).mockResolvedValue(SUMMARY);});
it("U77-C01 loads the resource summary only when cancellation starts",async()=>{
 const {user}=setup();expect(getCancellationPreview).not.toHaveBeenCalled();await open(user);expect(screen.getByText("3 × Projector")).toBeVisible();expect(screen.getByText("1 venue booking(s) will be withdrawn.")).toBeVisible();
});
it("U77-C02 requires consent and reason",async()=>{
 const {user}=setup();await open(user);await user.click(screen.getByRole("button",{name:"Confirm event cancellation"}));expect(screen.getByRole("alert")).toHaveTextContent("Confirm the resource release");expect(cancelEvent).not.toHaveBeenCalled();
});
it("U77-C03 keeps the event without cancelling",async()=>{
 const {user}=setup();await open(user);await user.click(screen.getByRole("button",{name:"Keep event"}));expect(screen.getByRole("button",{name:"Cancel event"})).toBeVisible();expect(cancelEvent).not.toHaveBeenCalled();
});
it("U77-C04 sends current version and reason and refreshes both resources",async()=>{
 const {user,invalidate}=setup();vi.mocked(cancelEvent).mockResolvedValue({event:9,status:"CANCELLED",released_equipment_reservations:1,withdrawn_venue_bookings:1});
 await open(user);await consent(user);await user.click(screen.getByRole("button",{name:"Confirm event cancellation"}));
 expect(cancelEvent).toHaveBeenCalledWith(9,"v1","Client cancelled");expect(await screen.findByRole("status")).toHaveTextContent("Event cancelled");
 await waitFor(()=>expect(invalidate).toHaveBeenCalledWith({queryKey:["equipment-availability"]}));expect(invalidate).toHaveBeenCalledWith({queryKey:["venue-availability"]});
});
it("U77-C05 stale-summary refusal resets consent",async()=>{
 const {user}=setup();vi.mocked(cancelEvent).mockRejectedValue(new Error("Arrangements changed. Reload."));
 await open(user);await consent(user);await user.click(screen.getByRole("button",{name:"Confirm event cancellation"}));
 expect(await screen.findByRole("alert")).toHaveTextContent("Arrangements changed");expect(screen.getByRole("checkbox")).not.toBeChecked();
});
it("U77-C06 blocks repeat submit or dismissal while pending",async()=>{
 const {user}=setup();vi.mocked(cancelEvent).mockReturnValue(new Promise(()=>{}));await open(user);await consent(user);
 const button=screen.getByRole("button",{name:"Confirm event cancellation"});await user.click(button);expect(button).toBeDisabled();expect(screen.getByRole("button",{name:"Keep event"})).toBeDisabled();
});
it("U77-C07 disables cancellation if summary cannot load",async()=>{
 vi.mocked(getCancellationPreview).mockRejectedValue(new Error("Forbidden"));const {user}=setup();await user.click(screen.getByRole("button",{name:"Cancel event"}));
 expect(await screen.findByRole("alert")).toHaveTextContent("could not load the current arrangements");expect(screen.getByRole("button",{name:"Confirm event cancellation"})).toBeDisabled();
});
it("U77-C08 does not submit while summary loads",async()=>{
 vi.mocked(getCancellationPreview).mockReturnValue(new Promise(()=>{}));const {user}=setup();await user.click(screen.getByRole("button",{name:"Cancel event"}));
 expect(screen.getByText("Loading current arrangements…")).toBeVisible();await consent(user);fireEvent.submit(screen.getByRole("button",{name:"Confirm event cancellation"}).closest("form")!);expect(cancelEvent).not.toHaveBeenCalled();
});
it.each(["DRAFT","CANCELLED","COMPLETED","REJECTED"] as const)("U77-C09 hides cancellation for %s",(status)=>{
 setup({...EVENT,status});expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("U77-C10 hides cancellation after event end",()=>{
 setup({...EVENT,preferred_end:"2020-01-01T00:00:00Z"});expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("U77-C11 changed resource summary needs renewed consent",async()=>{
 const {user,client}=setup();await open(user);await consent(user);expect(screen.getByRole("checkbox")).toBeChecked();
 client.setQueryData(["cancellation-preview",9],{...SUMMARY,version:"v2"});await waitFor(()=>expect(screen.getByRole("checkbox")).not.toBeChecked());
});
it("U77-C12 supports an undated event without resources",async()=>{
 vi.mocked(getCancellationPreview).mockResolvedValue({...SUMMARY,venue_bookings:[],equipment_reservations:[]});const {user}=setup({...EVENT,preferred_end:null});
 await user.click(screen.getByRole("button",{name:"Cancel event"}));expect(await screen.findByText("0 equipment reservation(s) will be released.")).toBeVisible();
});

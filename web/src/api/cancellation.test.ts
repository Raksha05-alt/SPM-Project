import { expect, it, vi } from "vitest";
import { request } from "./client";
import { cancelEvent, getCancellationPreview } from "./cancellation";
vi.mock("./client",()=>({request:vi.fn()}));
it("A77-C01 sends scoped preview and explicit versioned cancellation",()=>{
 getCancellationPreview(9);cancelEvent(9,"current-resource-version","Client cancelled");
 expect(request).toHaveBeenCalledWith("/api/events/9/cancellation-preview/");
 expect(request).toHaveBeenCalledWith("/api/events/9/cancel/",{method:"POST",body:{expected_version:"current-resource-version",confirm_cancel:true,reason:"Client cancelled"}});
});

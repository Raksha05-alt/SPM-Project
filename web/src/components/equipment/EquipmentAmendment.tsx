import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { amendEquipment, withdrawEquipment } from "../../api/equipmentPlans";
import type { EquipmentRequest } from "../../types";
import { inputClass } from "../Field";

export function EquipmentAmendment({ item, revision, refresh }: {
  item: EquipmentRequest; revision: number; refresh: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [quantity, setQuantity] = useState(String(item.quantity));
  const [requirements, setRequirements] = useState(item.technical_requirements);
  const [notice, setNotice] = useState("");
  const action = useMutation({
    mutationFn: (withdraw: boolean) => withdraw
      ? withdrawEquipment(item.id, revision)
      : amendEquipment(item.id, revision, Number(quantity), requirements),
    onSuccess: (_data, withdraw) => {
      setEditing(false); setConfirming(false);
      setNotice(withdraw ? "Request withdrawn and reservations released." : "Request amended. Technical Support has been notified.");
    },
    onSettled: refresh,
  });
  return <div className="mt-3">
    <button className="mr-4 underline" disabled={action.isPending} onClick={() => { setEditing(!editing); setConfirming(false); setQuantity(String(item.quantity)); setRequirements(item.technical_requirements); }}>Amend request</button>
    <button className="underline" disabled={action.isPending} onClick={() => { setConfirming(true); setEditing(false); }}>Withdraw request</button>
    {editing && <form onSubmit={(e) => { e.preventDefault(); action.mutate(false); }}>
      <label>Revised quantity<input className={inputClass} type="number" min="1" step="1" required value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
      <label>Revised technical requirements<textarea className={inputClass} value={requirements} onChange={(e) => setRequirements(e.target.value)} /></label>
      <button disabled={action.isPending} className="mt-2 underline">Save amendment</button>
    </form>}
    {confirming && <div>
      <p>Withdraw this request and release all its reserved equipment?</p>
      <button disabled={action.isPending} className="mr-4 underline" onClick={() => action.mutate(true)}>Confirm withdrawal</button>
      <button disabled={action.isPending} className="underline" onClick={() => setConfirming(false)}>Keep request</button>
    </div>}
    {action.error && <p role="alert">{action.error.message}</p>}
    {notice && <p role="status">{notice}</p>}
  </div>;
}

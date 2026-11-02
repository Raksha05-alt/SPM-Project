import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { releaseEquipment, type EquipmentReservation } from "../../api/equipmentPlans";
import { inputClass } from "../Field";

export function EquipmentRelease({ reservation, revision, refresh }: {
  reservation: EquipmentReservation; revision: number; refresh: () => Promise<unknown>;
}) {
  const [reason, setReason] = useState("");
  const [validation, setValidation] = useState<string | null>(null);
  const [released, setReleased] = useState(false);
  const action = useMutation({
    mutationFn: () => releaseEquipment(reservation.id, revision, reason.trim()),
    onSuccess: () => setReleased(true),
    onSettled: refresh,
  });
  return <div className="mt-3">
    {released && <p role="status">Equipment released. The coordinator has been notified.</p>}
    {action.error && <p role="alert">{action.error.message}</p>}
    {reservation.status === "ACTIVE" && !released && <form onSubmit={(event) => {
      event.preventDefault();
      if (!reason.trim()) { setValidation("Enter a reason for releasing the equipment."); return; }
      setValidation(null); action.mutate();
    }}>
      <p className="mb-2 text-sm">Release these {reservation.quantity} units so other events can use them. Technical approval and any current Safety check will need review.</p>
      <label>Release reason<textarea className={inputClass} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      {validation && <p role="alert">{validation}</p>}
      <button className="mt-2 rounded border border-rose-300 px-4 py-2 text-rose-800 disabled:opacity-50" disabled={action.isPending}>Release reservation #{reservation.id}</button>
    </form>}
  </div>;
}

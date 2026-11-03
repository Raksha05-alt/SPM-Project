import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { recordEquipmentUnavailable } from "../../api/confirmation";
import type { EquipmentRequest } from "../../types";

/** SCRUM-58 AC3 - Technical Support record, with a reason, that a request cannot be met. */
export function EquipmentUnavailable({
  item,
  refresh,
}: {
  item: EquipmentRequest;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const record = useMutation({
    mutationFn: () => recordEquipmentUnavailable(item.id, reason.trim()),
    onSuccess: (result) => {
      setNotice(result.detail);
      setOpen(false);
      setReason("");
    },
    onSettled: refresh,
  });
  const failed =
    record.error instanceof ApiError
      ? ((record.error.body as { detail?: string } | null)?.detail ?? "Could not record it.")
      : record.error
        ? "Could not record it."
        : null;

  return (
    <div className="mt-2 text-sm">
      {!open && (
        <button type="button" className="underline" onClick={() => setOpen(true)}>
          Record as unavailable
        </button>
      )}
      {open && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (reason.trim()) record.mutate();
          }}
        >
          <label className="block">
            Why is it unavailable?
            <textarea
              className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1"
              rows={2}
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <div className="mt-2 flex gap-2">
            <button
              type="submit"
              className="rounded bg-red-700 px-3 py-1 text-white disabled:opacity-50"
              disabled={!reason.trim() || record.isPending}
            >
              Record unavailable
            </button>
            <button type="button" className="underline" onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {notice && <p role="status">{notice}</p>}
      {failed && <p role="alert" className="text-red-700">{failed}</p>}
    </div>
  );
}

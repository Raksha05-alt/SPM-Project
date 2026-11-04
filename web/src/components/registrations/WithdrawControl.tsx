import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { getWithdrawalSummary, withdrawRegistration } from "../../api/registrations";

function when(value: string | null) {
  return value ? new Date(value).toLocaleString("en-SG") : "a date to be confirmed";
}

/** SCRUM-14 AC1 - a summary first; only an explicit confirmation withdraws. */
export function WithdrawControl({
  registrationId,
  label = "Withdraw",
  onDone,
}: {
  registrationId: number;
  label?: string;
  onDone: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const summary = useQuery({
    queryKey: ["withdrawal", registrationId],
    queryFn: () => getWithdrawalSummary(registrationId),
    enabled: asking,
  });
  const confirm = useMutation({
    mutationFn: () => withdrawRegistration(registrationId),
    onSuccess: () => {
      setAsking(false);
      onDone();
    },
  });
  const failed =
    confirm.error instanceof ApiError
      ? ((confirm.error.body as { detail?: string } | null)?.detail ?? "Could not withdraw.")
      : null;

  if (!asking) {
    return (
      <button type="button" className="mt-1 underline" onClick={() => setAsking(true)}>
        {label}
      </button>
    );
  }
  const data = summary.data;
  return (
    <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-3">
      {!data && <p className="text-slate-500">Loading…</p>}
      {data && (
        <>
          <p>
            {data.event_name}, {when(data.starts_at)}.
          </p>
          {data.can_withdraw ? (
            <p>
              {data.releases_place
                ? "Your place will be released for someone else."
                : "You will leave the waiting list."}
            </p>
          ) : (
            <p className="text-red-700">{data.reason}</p>
          )}
          <div className="mt-2 flex gap-2">
            {data.can_withdraw && (
              <button
                type="button"
                className="rounded-md bg-red-700 px-3 py-1 text-white disabled:opacity-50"
                disabled={confirm.isPending}
                onClick={() => confirm.mutate()}
              >
                Confirm withdrawal
              </button>
            )}
            <button type="button" className="underline" onClick={() => setAsking(false)}>
              Keep my place
            </button>
          </div>
        </>
      )}
      {failed && (
        <p role="alert" className="mt-2 text-red-700">
          {failed}
        </p>
      )}
    </div>
  );
}

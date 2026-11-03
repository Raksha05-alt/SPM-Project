import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { confirmEvent, getReadiness } from "../../api/confirmation";
import type { EventStatus } from "../../types";

const SHOWN_IN: EventStatus[] = ["APPROVED", "PLANNING", "CONFIRMED"];

/** SCRUM-58 - each essential arrangement, what is missing, and the Confirm action. */
export function ReadinessPanel({ eventId, status }: { eventId: number; status: EventStatus }) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["readiness", eventId, status],
    queryFn: () => getReadiness(eventId),
    enabled: SHOWN_IN.includes(status),
    refetchOnWindowFocus: "always",
  });
  const confirm = useMutation({
    mutationFn: () => confirmEvent(eventId),
    onSuccess: (result) => {
      setNotice(result.detail);
      queryClient.setQueryData(["event", eventId], result.event);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["readiness", eventId] });
      void queryClient.invalidateQueries({ queryKey: ["my-events"] });
    },
  });

  if (!SHOWN_IN.includes(status)) return null;
  if (isLoading) return <p className="text-slate-500">Checking the arrangements…</p>;
  if (isError || !data) return <p role="alert">We could not check the arrangements.</p>;

  // AC2 - a refused confirmation lists each missing item from the server.
  const refused =
    confirm.error instanceof ApiError
      ? ((confirm.error.body as { detail?: string; missing?: string[] } | null) ?? {})
      : confirm.error ? {} : null;

  return (
    <section aria-label="Readiness" className="mt-6 rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="mb-3 text-lg font-semibold text-navy-700">Readiness</h2>
      <ul className="space-y-1 text-sm">
        {data.items.map((item) => (
          <li key={`${item.area}-${item.label}`} className="flex gap-2">
            <span aria-hidden>{item.ready ? "✓" : "○"}</span>
            <span>
              <span className="font-medium">{item.area}:</span> {item.label}{" "}
              <span className="text-slate-500">
                ({item.ready ? "ready" : "not ready"}. {item.detail})
              </span>
            </span>
          </li>
        ))}
      </ul>

      {data.unavailable.length > 0 && (
        <div className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-900">
          <p className="font-medium">Unavailable</p>
          <ul className="list-inside list-disc">
            {data.unavailable.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {data.status === "CONFIRMED" ? (
        <p className="mt-4 text-sm text-green-800">
          Confirmed by {data.confirmed_by_name}
          {data.confirmed_at && ` on ${new Date(data.confirmed_at).toLocaleString("en-SG")}`}.
        </p>
      ) : (
        <>
          {data.missing.length > 0 && (
            <div className="mt-4 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <p className="font-medium">Still needed before confirmation:</p>
              <ul className="list-inside list-disc">
                {data.missing.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          )}
          <button
            type="button"
            className="mt-4 rounded-md bg-navy-700 px-4 py-2 text-white disabled:opacity-50"
            disabled={!data.can_confirm || confirm.isPending}
            onClick={() => {
              setNotice(null);
              confirm.mutate();
            }}
          >
            Confirm event
          </button>
        </>
      )}

      {notice && (
        <p role="status" className="mt-2 text-sm text-green-800">
          {notice}
        </p>
      )}
      {refused && (
        <div role="alert" className="mt-2 text-sm text-red-700">
          <p>{refused.detail ?? "The event could not be confirmed."}</p>
          {refused.missing && refused.missing.length > 0 && (
            <ul className="list-inside list-disc">
              {refused.missing.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

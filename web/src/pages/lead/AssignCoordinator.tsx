import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { assignCoordinator, listCoordinatorOptions } from "../../api/lead";
import type { EventRequest } from "../../types";

export function LeadNav() {
  return (
    <nav className="mb-4 flex gap-4 text-sm">
      <Link to="/lead" className="text-navy-700 underline">
        Unassigned requests
      </Link>
      <Link to="/lead/assignments" className="text-navy-700 underline">
        All assignments
      </Link>
    </nav>
  );
}

/**
 * Week 7 change 5 - a Lead chooses a suitable coordinator, seeing who is available
 * and how many active events each already has.
 */
export function AssignCoordinator({
  eventId,
  eventName,
  current,
  onAssigned,
}: {
  eventId: number;
  eventName: string;
  current: number | null;
  onAssigned?: (event: EventRequest) => void;
}) {
  const queryClient = useQueryClient();
  const { data: coordinators } = useQuery({
    queryKey: ["coordinator-options"],
    queryFn: listCoordinatorOptions,
  });
  const [choice, setChoice] = useState("");
  const assign = useMutation({
    mutationFn: () => assignCoordinator(eventId, Number(choice)),
    onSuccess: (updated) => {
      setChoice("");
      void queryClient.invalidateQueries({ queryKey: ["lead"] });
      void queryClient.invalidateQueries({ queryKey: ["coordinator-options"] });
      onAssigned?.(updated);
    },
  });
  const verb = current ? "Reassign" : "Assign";

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor={`coordinator-for-${eventId}`}>
          Coordinator for {eventName}
        </label>
        <select
          id={`coordinator-for-${eventId}`}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
        >
          <option value="">Choose a coordinator</option>
          {(coordinators ?? [])
            .filter((c) => c.id !== current)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.active_events} active{c.available ? "" : " · unavailable"}
              </option>
            ))}
        </select>
        <button
          type="button"
          disabled={!choice || assign.isPending}
          onClick={() => assign.mutate()}
          className="rounded-md bg-navy-700 px-3 py-1 text-sm font-medium text-white hover:bg-navy-600 disabled:opacity-50"
          aria-label={`${verb} ${eventName}`}
        >
          {verb}
        </button>
      </div>
      {assign.error && (
        <p role="alert" className="mt-1 text-xs font-medium text-rose-700">
          {assign.error.message}
        </p>
      )}
    </div>
  );
}

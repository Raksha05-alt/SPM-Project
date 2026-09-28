/** Who approved an event and when - shown to internal users only. */
export function ApprovalNote({
  approvedBy,
  approvedAt,
}: {
  approvedBy: string | null;
  approvedAt: string | null;
}) {
  if (!approvedBy || !approvedAt) return null;
  return (
    <p className="mt-1 text-xs text-slate-500">
      Approved by {approvedBy} · {new Date(approvedAt).toLocaleString("en-SG")}
    </p>
  );
}

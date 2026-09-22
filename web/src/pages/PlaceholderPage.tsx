export function PlaceholderPage({ title, sprint }: { title: string; sprint: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center">
      <h1 className="mb-2 text-xl font-semibold text-navy-700">{title}</h1>
      <p className="text-sm text-slate-500">
        This area arrives in {sprint}. The route exists now so that sign-in lands every role
        somewhere sensible.
      </p>
    </div>
  );
}

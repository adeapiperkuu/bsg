export function SectionLabel({ title, count }: { title: string; count?: number }) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h4>
      {count !== undefined && count > 0 ? (
        <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-foreground">
          {count}
        </span>
      ) : null}
    </div>
  );
}

export function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="mt-1 text-[11px] text-[color:var(--danger)]">{message}</p>;
}

export function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="mt-2 text-[11px] text-[color:var(--danger)]">{message}</p>;
}

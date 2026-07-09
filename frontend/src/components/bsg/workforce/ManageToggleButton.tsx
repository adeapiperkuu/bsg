import { cn } from "@/lib/utils";

export function ManageToggleButton({
  active,
  onClick,
  label = "Manage",
}: {
  active: boolean;
  onClick: () => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded border px-2.5 py-1 text-[11px] font-medium",
        active
          ? "border-[color:var(--brand)]/30 bg-[color:var(--brand)]/10 text-[color:var(--brand)]"
          : "border-border bg-elevated text-foreground hover:bg-card",
      )}
    >
      {active ? "Hide" : label}
    </button>
  );
}

import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

type Props = {
  className?: string;
  label?: string;
};

export function PageLoadingScreen({ className, label = "Loading…" }: Props) {
  return (
    <div
      className={cn(
        "flex min-h-[calc(100vh-11.5rem)] flex-col items-center justify-center gap-3 xl:min-h-[44rem]",
        className,
      )}
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={label}
    >
      <Loader2 className="h-8 w-8 animate-spin text-[color:var(--brand)]" />
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

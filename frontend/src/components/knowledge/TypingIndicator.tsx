import { cn } from "@/lib/utils";

type Props = {
  label?: string;
  className?: string;
};

export function TypingIndicator({ label, className }: Props) {
  return (
    <span
      className={cn("inline-flex items-center gap-1.5", className)}
      aria-label={label ?? "Typing"}
    >
      {label ? <span>{label}</span> : null}
      <span className="inline-flex items-center gap-0.5" aria-hidden="true">
        {[0, 1, 2].map((index) => (
          <span
            key={index}
            className="h-1 w-1 rounded-full bg-current opacity-60 animate-bounce"
            style={{ animationDelay: `${index * 140}ms`, animationDuration: "900ms" }}
          />
        ))}
      </span>
    </span>
  );
}

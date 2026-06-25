import { DELIVERY_SUGGESTED_PROMPTS } from "@/types/delivery-chat";

type Props = {
  disabled?: boolean;
  onSelect: (prompt: string) => void;
};

export function DeliverySuggestions({ disabled, onSelect }: Props) {
  return (
    <div>
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Suggested prompts
      </div>
      <div className="flex flex-wrap gap-1.5">
        {DELIVERY_SUGGESTED_PROMPTS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(suggestion)}
            className="rounded-full border border-border bg-elevated px-2.5 py-1 text-[11px] hover:bg-card disabled:cursor-not-allowed disabled:opacity-50"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

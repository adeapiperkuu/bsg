import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";

type Props = {
  value: string;
  disabled?: boolean;
  asking?: boolean;
  replying?: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
};

export function DeliveryChatInput({
  value,
  disabled,
  asking,
  replying,
  onChange,
  onSubmit,
}: Props) {
  return (
    <form
      className="flex gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <input
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder="Ask about delivery…"
        className="min-h-10 flex-1 rounded-md border border-border bg-card px-3 py-2 text-xs outline-none focus:border-[color:var(--brand)] disabled:opacity-50"
      />
      <Button
        type="submit"
        disabled={disabled || !value.trim()}
        className="h-10 gap-2 bg-[color:var(--brand)] px-4 text-xs text-[color:var(--brand-foreground)]"
      >
        <Send className="h-3.5 w-3.5" />
        {asking ? "Asking" : replying ? "Replying" : "Send"}
      </Button>
    </form>
  );
}

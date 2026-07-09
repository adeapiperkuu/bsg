import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WORKFORCE_CHAT_MAX_MESSAGE_LENGTH } from "./constants";

type Props = {
  value: string;
  disabled?: boolean;
  asking?: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
};

const COUNTER_WARNING_THRESHOLD = WORKFORCE_CHAT_MAX_MESSAGE_LENGTH - 200;

export function WorkforceAgentComposer({ value, disabled, asking, onChange, onSubmit }: Props) {
  const overLimit = value.length > WORKFORCE_CHAT_MAX_MESSAGE_LENGTH;

  return (
    <form
      className="flex flex-col gap-1"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="flex gap-2">
        <input
          value={value}
          disabled={disabled}
          maxLength={WORKFORCE_CHAT_MAX_MESSAGE_LENGTH}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
          }}
          placeholder="Ask about workforce capability…"
          className="min-h-10 flex-1 rounded-md border border-border bg-card px-3 py-2 text-xs outline-none focus:border-[color:var(--brand)] disabled:opacity-50"
        />
        <Button
          type="submit"
          disabled={disabled || !value.trim() || overLimit}
          className="h-10 gap-2 bg-[color:var(--brand)] px-4 text-xs text-[color:var(--brand-foreground)]"
        >
          <Send className="h-3.5 w-3.5" />
          {asking ? "Asking" : "Send"}
        </Button>
      </div>
      {value.length >= COUNTER_WARNING_THRESHOLD && (
        <span
          className={
            overLimit
              ? "text-[10px] text-[color:var(--danger)]"
              : "text-[10px] text-muted-foreground"
          }
        >
          {value.length}/{WORKFORCE_CHAT_MAX_MESSAGE_LENGTH} characters
        </span>
      )}
    </form>
  );
}

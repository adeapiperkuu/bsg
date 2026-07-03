import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DELIVERY_CHAT_MAX_MESSAGE_LENGTH } from "@/types/delivery-chat";

type Props = {
  value: string;
  disabled?: boolean;
  asking?: boolean;
  replying?: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
};

// Start showing a remaining-character count once the user is close to the limit,
// rather than cluttering the input at all times.
const COUNTER_WARNING_THRESHOLD = DELIVERY_CHAT_MAX_MESSAGE_LENGTH - 200;

export function DeliveryChatInput({
  value,
  disabled,
  asking,
  replying,
  onChange,
  onSubmit,
}: Props) {
  const overLimit = value.length > DELIVERY_CHAT_MAX_MESSAGE_LENGTH;

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
          maxLength={DELIVERY_CHAT_MAX_MESSAGE_LENGTH}
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
          disabled={disabled || !value.trim() || overLimit}
          className="h-10 gap-2 bg-[color:var(--brand)] px-4 text-xs text-[color:var(--brand-foreground)]"
        >
          <Send className="h-3.5 w-3.5" />
          {asking ? "Asking" : replying ? "Replying" : "Send"}
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
          {value.length}/{DELIVERY_CHAT_MAX_MESSAGE_LENGTH} characters
        </span>
      )}
    </form>
  );
}

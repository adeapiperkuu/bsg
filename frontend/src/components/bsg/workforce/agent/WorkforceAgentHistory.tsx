import { useState } from "react";
import { History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatSessionTime } from "./session-utils";
import type { WorkforceChatSession } from "./types";

type Props = {
  asking: boolean;
  activeSessionId: string | null;
  sessions: WorkforceChatSession[];
  onSelectSession: (sessionId: string) => void;
};

export function WorkforceAgentHistory({
  asking,
  activeSessionId,
  sessions,
  onSelectSession,
}: Props) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={asking}
          className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
        >
          <History className="h-3.5 w-3.5" />
          History
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-2">
        <div className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Session conversations
        </div>
        {sessions.length === 0 ? (
          <p className="px-1 py-2 text-xs text-muted-foreground">
            No conversations yet this session.
          </p>
        ) : (
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {sessions.map((session) => {
              const isActive = activeSessionId === session.id;
              const questionCount = session.messages.filter(
                (message) => message.role === "user",
              ).length;
              return (
                <button
                  key={session.id}
                  type="button"
                  disabled={asking}
                  onClick={() => {
                    onSelectSession(session.id);
                    setOpen(false);
                  }}
                  className={`w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors disabled:opacity-50 ${
                    isActive ? "bg-secondary/80 ring-1 ring-border" : "hover:bg-secondary"
                  }`}
                >
                  <span className="line-clamp-2 font-medium text-foreground">{session.title}</span>
                  <span className="mt-0.5 block text-[10px] text-muted-foreground">
                    {questionCount} question{questionCount === 1 ? "" : "s"} ·{" "}
                    {formatSessionTime(session.updatedAt)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

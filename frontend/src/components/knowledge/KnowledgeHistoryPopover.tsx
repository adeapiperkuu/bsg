import { useEffect, useState } from "react";
import { History } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useKnowledgeConversationsQuery } from "@/lib/queries/knowledge";
import type { KnowledgeConversationSummaryApi } from "@/types/knowledge";

type KnowledgeHistoryPopoverProps = {
  asking: boolean;
  activeConversationId?: string | null;
  onSelectConversation: (conversation: KnowledgeConversationSummaryApi) => void | Promise<void>;
};

export function KnowledgeHistoryPopover({
  asking,
  activeConversationId,
  onSelectConversation,
}: KnowledgeHistoryPopoverProps) {
  const [open, setOpen] = useState(false);
  const historyQuery = useKnowledgeConversationsQuery(open);
  const conversations = historyQuery.data ?? [];
  const loading = open && historyQuery.isFetching && conversations.length === 0;

  useEffect(() => {
    if (open) {
      void historyQuery.refetch();
    }
  }, [historyQuery.refetch, open]);

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
          Saved conversations
        </div>
        {loading ? (
          <p className="px-1 py-2 text-xs text-muted-foreground">Loading conversations...</p>
        ) : historyQuery.isError ? (
          <p className="px-1 py-2 text-xs text-destructive">Could not load saved conversations.</p>
        ) : conversations.length === 0 ? (
          <p className="px-1 py-2 text-xs text-muted-foreground">No saved conversations yet.</p>
        ) : (
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {conversations.map((conversation) => {
              const isActive = activeConversationId === conversation.id;
              return (
                <button
                  key={conversation.id}
                  type="button"
                  disabled={asking}
                  onClick={() => {
                    void onSelectConversation(conversation);
                    setOpen(false);
                  }}
                  className={`w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-secondary disabled:opacity-50 ${
                    isActive ? "bg-secondary/80 ring-1 ring-border" : ""
                  }`}
                >
                  <span className="line-clamp-2 font-medium text-foreground">{conversation.title}</span>
                  <span className="mt-0.5 block text-[10px] text-muted-foreground">
                    {conversation.turn_count} question{conversation.turn_count === 1 ? "" : "s"} ·{" "}
                    {new Date(conversation.updated_at).toLocaleString()}
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

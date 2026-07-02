import { useState } from "react";
import { History } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useKnowledgeAgentQueriesQuery } from "@/lib/queries/knowledge";
import type { AgentQueryApi } from "@/types/knowledge";

type KnowledgeHistoryPopoverProps = {
  asking: boolean;
  onSelectQuery: (query: AgentQueryApi) => void | Promise<void>;
};

export function KnowledgeHistoryPopover({ asking, onSelectQuery }: KnowledgeHistoryPopoverProps) {
  const [open, setOpen] = useState(false);
  const historyQuery = useKnowledgeAgentQueriesQuery(open);
  const queryHistory = historyQuery.data ?? [];
  const loading = open && historyQuery.isFetching && queryHistory.length === 0;

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
          Recent knowledge answers
        </div>
        {loading ? (
          <p className="px-1 py-2 text-xs text-muted-foreground">Loading saved answers...</p>
        ) : queryHistory.length === 0 ? (
          <p className="px-1 py-2 text-xs text-muted-foreground">No saved answers yet.</p>
        ) : (
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {queryHistory.map((query) => (
              <button
                key={query.id}
                type="button"
                disabled={asking}
                onClick={() => void onSelectQuery(query)}
                className="w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-secondary disabled:opacity-50"
              >
                <span className="line-clamp-2 font-medium text-foreground">{query.query_text}</span>
                <span className="mt-0.5 block text-[10px] text-muted-foreground">
                  {new Date(query.created_at).toLocaleString()}
                </span>
              </button>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

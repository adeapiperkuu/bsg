import type { AgentQueryRead } from "@/types/workforce";

export function WorkforceAgentAnswer({ answer }: { answer: AgentQueryRead }) {
  const evidence = answer.evidence_links ?? [];
  return (
    <div className="rounded-md border border-border bg-elevated/50 p-3">
      <p className="whitespace-pre-wrap text-xs text-foreground">{answer.answer_text}</p>
      {evidence.length > 0 && (
        <div className="mt-3 border-t border-border/60 pt-2">
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Evidence ({evidence.length})
          </div>
          <ul className="space-y-1">
            {evidence.map((link, index) => (
              <li
                key={link.id ?? `${link.source_table}:${link.source_row_id}:${index}`}
                className="flex items-center gap-2 text-[11px] text-muted-foreground"
              >
                <span className="rounded bg-secondary px-1.5 py-0.5 font-medium text-foreground">
                  {link.source_table}
                </span>
                <span className="truncate font-mono text-[10px]">
                  {link.source_row_id.slice(0, 8)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {(answer.model_used || answer.latency_ms !== null) && (
        <div className="mt-2 text-[10px] text-muted-foreground">
          {answer.model_used ? `Model: ${answer.model_used}` : "Deterministic answer"}
          {answer.latency_ms !== null ? ` / ${answer.latency_ms} ms` : ""}
        </div>
      )}
    </div>
  );
}

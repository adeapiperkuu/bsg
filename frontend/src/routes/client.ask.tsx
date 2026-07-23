import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, History, Plus, Send, Sparkles } from "lucide-react";

import { AiBadge, Card } from "@/components/bsg/widgets";
import { TypingIndicator } from "@/components/knowledge/TypingIndicator";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { summarizeClientPortfolio } from "@/features/client-dashboard/client-dashboard-utils";
import {
  useClientAskQueryHistory,
  useCreateClientAskQueryMutation,
} from "@/lib/queries/client-ask";
import { deliveryPortfolioQueryOptions } from "@/lib/queries/delivery";
import { cn } from "@/lib/utils";
import type { ClientIntelligenceQueryRead } from "@/types/client-intelligence";

export const Route = createFileRoute("/client/ask")({ component: Ask });

const WELCOME_SUB =
  "Ask about project health, delivery, milestones, risks, team capacity, quality, governance, and approved reports. Answers use governed, client-safe facts for this project.";

const SUGGESTED_QUESTIONS = [
  "What was completed this week?",
  "What risks are affecting the project?",
  "When is the next milestone?",
  "Show me the latest project report.",
  "What is the current delivery confidence?",
  "Are any client actions overdue?",
] as const;

type ChatMsg = {
  id: string;
  role: "ai" | "user";
  text: string;
  pending?: boolean;
  error?: boolean;
};

function formatAnswer(result: ClientIntelligenceQueryRead): string {
  const parts = [result.answer_text.trim()];
  // Never dump internal DQ / source-gap codes to clients — keep the chat human-readable.
  if (result.next_step?.trim()) {
    parts.push(result.next_step.trim());
  }
  return parts.filter(Boolean).join("\n\n");
}

function historyToMessages(items: ClientIntelligenceQueryRead[]): ChatMsg[] {
  const chronological = [...items].reverse();
  const messages: ChatMsg[] = [];
  for (const item of chronological) {
    messages.push({
      id: `${item.query_id}-q`,
      role: "user",
      text: item.question,
    });
    messages.push({
      id: `${item.query_id}-a`,
      role: "ai",
      text: formatAnswer(item),
    });
  }
  return messages;
}

function formatHistoryDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Saved answer"
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function Ask() {
  const portfolioQuery = useQuery(deliveryPortfolioQueryOptions);
  const portfolio = summarizeClientPortfolio(portfolioQuery.data);
  const projects = portfolio.projects;
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const [projectId, setProjectId] = useState<string>("");
  const [draft, setDraft] = useState("");
  const [localMessages, setLocalMessages] = useState<ChatMsg[]>([]);
  const [sendError, setSendError] = useState<string | null>(null);
  const [threadCleared, setThreadCleared] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    if (!projectId && projects.length > 0) {
      setProjectId(projects[0].id);
    }
  }, [projectId, projects]);

  const historyQuery = useClientAskQueryHistory(projectId || null);
  const askMutation = useCreateClientAskQueryMutation();
  const asking = askMutation.isPending;

  const historyMessages = useMemo(
    () => (threadCleared ? [] : historyToMessages(historyQuery.data?.items ?? [])),
    [historyQuery.data?.items, threadCleared],
  );

  const messages = useMemo(() => {
    const byId = new Map<string, ChatMsg>();
    for (const msg of historyMessages) byId.set(msg.id, msg);
    for (const msg of localMessages) byId.set(msg.id, msg);
    return Array.from(byId.values());
  }, [historyMessages, localMessages]);

  const hasUserMessage = messages.some((msg) => msg.role === "user");

  useEffect(() => {
    if (!historyQuery.data?.items?.length || threadCleared) return;
    const known = new Set(historyQuery.data.items.map((item) => item.query_id));
    setLocalMessages((prev) =>
      prev.filter((msg) => {
        const queryId = msg.id.replace(/-(q|a)$/, "");
        return !known.has(queryId);
      }),
    );
  }, [historyQuery.data?.items, threadCleared]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [asking, messages.length]);

  const canSend =
    Boolean(projectId) && draft.trim().length > 0 && !asking && !portfolioQuery.isLoading;

  const clearThread = () => {
    setLocalMessages([]);
    setSendError(null);
    setDraft("");
    setThreadCleared(true);
  };

  const send = (rawQuestion?: string) => {
    const question = (rawQuestion ?? draft).trim();
    if (!projectId || !question || asking) return;

    const pendingId = `pending-${Date.now()}`;
    setSendError(null);
    setDraft("");
    setLocalMessages((prev) => [...prev, { id: `${pendingId}-q`, role: "user", text: question }]);

    askMutation.mutate(
      { projectId, question },
      {
        onSuccess: (result) => {
          setLocalMessages((prev) => {
            const withoutPending = prev.filter((msg) => msg.id !== `${pendingId}-q`);
            return [
              ...withoutPending,
              { id: `${result.query_id}-q`, role: "user", text: result.question },
              { id: `${result.query_id}-a`, role: "ai", text: formatAnswer(result) },
            ];
          });
        },
        onError: (error) => {
          const message =
            error instanceof Error ? error.message : "Failed to get an answer. Please try again.";
          setSendError(message);
          setLocalMessages((prev) => [
            ...prev.filter((msg) => msg.id !== `${pendingId}-q`),
            { id: `${pendingId}-q`, role: "user", text: question },
            {
              id: `${pendingId}-a`,
              role: "ai",
              error: true,
              text: "I could not answer that right now. Please try again, or contact your BSG PM.",
            },
          ]);
        },
      },
    );
  };

  const selectedProjectName =
    projects.find((project) => project.id === projectId)?.name ?? "Select a project";

  return (
    <Card className="flex min-h-[640px] flex-col border-transparent bg-card/80 p-0">
      <div className="border-b border-border/70 px-5 py-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
                <Bot className="h-4 w-4" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold tracking-tight text-foreground">
                    Ask Agent
                  </h3>
                  <AiBadge label="AI BETA" />
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Your project intelligence, in one place
                </p>
                {projectId ? (
                  <span className="mt-1.5 inline-flex rounded-full border border-[color:var(--brand)]/25 bg-[color:var(--brand)]/8 px-2.5 py-0.5 text-[10px] font-medium text-[color:var(--brand)]">
                    {selectedProjectName}
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {portfolioQuery.isError ? (
              <button
                type="button"
                className="text-[11px] text-[color:var(--danger)] underline"
                onClick={() => void portfolioQuery.refetch()}
              >
                Retry projects
              </button>
            ) : projects.length > 0 ? (
              <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="sr-only">Project</span>
                <select
                  value={projectId}
                  onChange={(e) => {
                    setProjectId(e.target.value);
                    setLocalMessages([]);
                    setSendError(null);
                    setThreadCleared(false);
                  }}
                  disabled={portfolioQuery.isLoading || asking}
                  className="h-8 max-w-[220px] rounded-md border border-border/70 bg-card px-2.5 text-xs text-foreground outline-none focus:border-[color:var(--brand)] disabled:opacity-60"
                >
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            <Popover open={historyOpen} onOpenChange={setHistoryOpen}>
              <PopoverTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={!projectId || asking}
                  className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
                >
                  <History className="h-3.5 w-3.5" />
                  History
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-[min(24rem,calc(100vw-2rem))] p-2">
                <div className="mb-2 flex items-center justify-between gap-3 px-1">
                  <div>
                    <p className="text-xs font-semibold text-foreground">Past questions</p>
                    <p className="mt-0.5 text-[10px] text-muted-foreground">
                      Saved answers for {selectedProjectName}
                    </p>
                  </div>
                  {historyQuery.data?.total ? (
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">
                      {historyQuery.data.total}
                    </span>
                  ) : null}
                </div>
                {historyQuery.isLoading ? (
                  <p className="px-1 py-3 text-xs text-muted-foreground">Loading past questions…</p>
                ) : historyQuery.isError ? (
                  <p className="px-1 py-3 text-xs text-[color:var(--danger)]">
                    Could not load history.{" "}
                    <button
                      type="button"
                      className="underline"
                      onClick={() => void historyQuery.refetch()}
                    >
                      Retry
                    </button>
                  </p>
                ) : !historyQuery.data?.items.length ? (
                  <p className="px-1 py-3 text-xs text-muted-foreground">
                    No past questions for this project yet.
                  </p>
                ) : (
                  <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
                    {historyQuery.data.items.map((item) => (
                      <article
                        key={item.query_id}
                        className="rounded-md border border-border/70 bg-card p-2.5"
                      >
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--brand)]">
                          You · {formatHistoryDate(item.created_at)}
                        </p>
                        <p className="mt-1 text-xs font-medium leading-5 text-foreground">
                          {item.question}
                        </p>
                        <p className="mt-2 whitespace-pre-wrap text-[11px] leading-5 text-muted-foreground">
                          {formatAnswer(item)}
                        </p>
                      </article>
                    ))}
                  </div>
                )}
              </PopoverContent>
            </Popover>

            {messages.length > 0 || asking ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={asking}
                className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
                onClick={clearThread}
              >
                <Plus className="h-3.5 w-3.5" />
                New chat
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="relative mx-5 mt-4 min-h-0 flex-1">
        <div className="h-full max-h-[480px] min-h-[280px] space-y-4 overflow-y-auto rounded-md bg-secondary/35 p-4 text-xs">
          {projects.length === 0 && !portfolioQuery.isLoading ? (
            <div className="flex h-full min-h-[220px] flex-col items-center justify-center px-2 py-6 text-center">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-card text-[color:var(--brand)]">
                <Sparkles className="h-5 w-5" />
              </div>
              <p className="text-sm font-medium text-foreground">No projects assigned yet</p>
              <p className="mt-1 max-w-sm text-[11px] leading-4 text-muted-foreground">
                Ask Agent unlocks once a project is assigned to your account.
              </p>
            </div>
          ) : historyQuery.isLoading && projectId && !hasUserMessage && !asking ? (
            <div className="flex flex-col items-center justify-center gap-2 py-8 text-center text-muted-foreground">
              <p className="text-[11px]">Loading previous questions…</p>
            </div>
          ) : !hasUserMessage && !asking ? (
            <div className="flex h-full min-h-[220px] flex-col items-center justify-center px-2 py-6 text-center">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-card text-[color:var(--brand)]">
                <Sparkles className="h-5 w-5" />
              </div>
              <p className="text-sm font-medium text-foreground">Ask anything about this project</p>
              <p className="mt-1 max-w-sm text-[11px] leading-4 text-muted-foreground">
                {WELCOME_SUB}
              </p>
              <div className="mt-5 flex max-w-md flex-wrap justify-center gap-2">
                {SUGGESTED_QUESTIONS.map((question) => (
                  <button
                    key={question}
                    type="button"
                    disabled={!projectId || asking}
                    onClick={() => send(question)}
                    className="rounded-full border border-border/70 bg-card px-3 py-1.5 text-left text-[11px] text-muted-foreground transition-colors hover:border-[color:var(--brand)]/30 hover:bg-secondary/70 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {question}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {historyQuery.isError && projectId ? (
            <p className="text-[11px] text-[color:var(--danger)]" role="alert">
              Failed to load history.{" "}
              <button
                type="button"
                className="underline"
                onClick={() => void historyQuery.refetch()}
              >
                Retry
              </button>
            </p>
          ) : null}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn("flex gap-3", msg.role === "user" ? "justify-end" : "justify-start")}
            >
              {msg.role === "ai" ? (
                <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground">
                  <Bot className="h-3.5 w-3.5" />
                </div>
              ) : null}
              <div
                className={cn(
                  "max-w-[88%] rounded-md px-3 py-3",
                  msg.role === "user"
                    ? "bg-[color:var(--brand)] text-[color:var(--brand-foreground)]"
                    : "bg-card",
                  msg.error && "border border-[color:var(--danger)]/30 bg-[color:var(--danger)]/5",
                )}
              >
                <div
                  className={cn(
                    "mb-1 text-[10px] font-semibold uppercase tracking-wider",
                    msg.role === "user" ? "text-white/70" : "text-muted-foreground",
                  )}
                >
                  {msg.role === "user" ? "You" : "BSG Agent"}
                </div>
                <p className="whitespace-pre-wrap text-[11px] leading-5">{msg.text}</p>
              </div>
            </div>
          ))}

          {asking ? (
            <div className="flex gap-3">
              <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground">
                <Bot className="h-3.5 w-3.5" />
              </div>
              <div className="rounded-md bg-card px-3 py-3 text-xs text-muted-foreground">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  BSG Agent
                </div>
                <TypingIndicator label="Looking up governed evidence" />
              </div>
            </div>
          ) : null}

          <div ref={chatEndRef} aria-hidden="true" />
        </div>
      </div>

      <div className="border-t border-border/70 p-5 pt-4">
        {sendError ? (
          <p className="mb-2 text-[11px] text-[color:var(--danger)]" role="alert">
            {sendError}
          </p>
        ) : null}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Ask about this project…"
            disabled={!projectId || asking}
            className="min-h-10 flex-1 rounded-md border border-border bg-card px-3 py-2 text-xs outline-none focus:border-[color:var(--brand)] disabled:opacity-50"
          />
          <Button
            type="submit"
            disabled={!canSend}
            className="h-10 gap-2 bg-[color:var(--brand)] px-4 text-xs text-[color:var(--brand-foreground)]"
          >
            <Send className="h-3.5 w-3.5" />
            {asking ? "Asking" : "Ask"}
          </Button>
        </form>
      </div>
    </Card>
  );
}

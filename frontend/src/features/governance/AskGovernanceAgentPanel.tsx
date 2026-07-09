import { useMutation } from "@tanstack/react-query";
import { Bot, Check, Copy, RefreshCw, Send, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Card, EvidenceBadge, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { TypingIndicator } from "@/components/knowledge/TypingIndicator";
import { TypewriterText } from "@/components/knowledge/TypewriterText";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { createAgentQuery } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AgentQueryEvidenceLinkRead, AgentQueryRead } from "@/types/workforce";

type ProjectOption = {
  value: string;
  label: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "agent";
  text: string;
  answer?: AgentQueryRead;
  isStreaming?: boolean;
  isServiceError?: boolean;
};

const ALL_PROJECTS_VALUE = "__all_projects__";
const TYPEWRITER_MAX_CHARS = 4000;
const GOVERNANCE_SUGGESTIONS = [
  "What are the top governance risks?",
  "Which dependencies threaten timelines?",
  "Which projects have unresolved escalations?",
  "What actions are overdue this week?",
  "Which projects need leadership attention?",
  "Summarize governance posture for this project.",
];

function createMessageId() {
  return crypto.randomUUID();
}

function sourceLabel(sourceTable: string): string {
  if (sourceTable.startsWith("governance") || sourceTable.startsWith("project_")) {
    return "Governance";
  }
  if (sourceTable.startsWith("knowledge")) return "Knowledge";
  if (
    sourceTable === "risk_alerts" ||
    sourceTable === "milestones" ||
    sourceTable === "delivery_confidence_scores"
  ) {
    return "Delivery";
  }
  if (sourceTable.startsWith("quality")) return "Quality";
  if (sourceTable.includes("capability") || sourceTable.includes("utilization")) return "Workforce";
  return "Evidence";
}

function confidenceStatus(confidence?: string | null): string {
  if (confidence === "high") return "High";
  if (confidence === "medium") return "Medium";
  return "Low";
}

function confidencePercent(confidence?: string | null): number {
  if (confidence === "high") return 90;
  if (confidence === "medium") return 70;
  return 45;
}

function shouldAnimateAnswer(text: string) {
  return text.trim().length > 0 && text.length <= TYPEWRITER_MAX_CHARS;
}

function groupedEvidence(links: AgentQueryEvidenceLinkRead[]) {
  return links.reduce<Record<string, AgentQueryEvidenceLinkRead[]>>((groups, item) => {
    const label = sourceLabel(item.source_table);
    groups[label] = groups[label] ?? [];
    groups[label].push(item);
    return groups;
  }, {});
}

function buildFallbackAnswer(queryText: string, selectedProjectId: string): AgentQueryRead {
  return {
    id: createMessageId(),
    agent_name: "project_governance_agent",
    project_id: selectedProjectId === ALL_PROJECTS_VALUE ? null : selectedProjectId,
    query_text: queryText,
    answer_text: "I could not retrieve approved governance evidence for that question.",
    model_used: null,
    latency_ms: null,
    created_at: new Date().toISOString(),
    evidence_links: [],
    confidence_level: "low",
    insufficient_evidence: true,
    related_records: [],
    source_agents_used: [],
  };
}

export function AskGovernanceAgentPanel({ projects }: { projects: ProjectOption[] }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<string>(ALL_PROJECTS_VALUE);
  const [selectedAgentMessageId, setSelectedAgentMessageId] = useState<string | null>(null);
  const [animatingMessageId, setAnimatingMessageId] = useState<string | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);

  const selectedAgentMessage =
    messages.find((message) => message.id === selectedAgentMessageId && message.role === "agent") ??
    [...messages].reverse().find((message) => message.role === "agent");
  const selectedAnswer = selectedAgentMessage?.answer;
  const evidenceGroups = useMemo(
    () => groupedEvidence(selectedAnswer?.evidence_links ?? []),
    [selectedAnswer],
  );

  const askMutation = useMutation({
    mutationFn: async (queryText: string) =>
      createAgentQuery({
        agent_name: "project_governance_agent",
        project_id: selectedProjectId === ALL_PROJECTS_VALUE ? null : selectedProjectId,
        query_text: queryText,
      }),
  });

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const chatScroll = chatScrollRef.current;
      if (!chatScroll) return;

      chatScroll.scrollTo({
        top: chatScroll.scrollHeight,
        behavior: "smooth",
      });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [messages, animatingMessageId]);

  const finishAgentAnswer = (messageId: string, text: string) => {
    if (shouldAnimateAnswer(text)) {
      setAnimatingMessageId(messageId);
    }
  };

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || askMutation.isPending) return;

    const agentMessageId = createMessageId();
    setMessages((current) => [
      ...current,
      { id: createMessageId(), role: "user", text: trimmed },
      { id: agentMessageId, role: "agent", text: "", isStreaming: true },
    ]);
    setSelectedAgentMessageId(agentMessageId);
    setInput("");

    try {
      const answer = await askMutation.mutateAsync(trimmed);
      setMessages((current) =>
        current.map((message) =>
          message.id === agentMessageId
            ? {
                ...message,
                text: answer.answer_text,
                answer,
                isStreaming: false,
              }
            : message,
        ),
      );
      finishAgentAnswer(agentMessageId, answer.answer_text);
    } catch (error) {
      const fallback = buildFallbackAnswer(trimmed, selectedProjectId);
      toast.error(error instanceof Error ? error.message : "Ask Governance Agent failed.");
      setMessages((current) =>
        current.map((message) =>
          message.id === agentMessageId
            ? {
                ...message,
                text: fallback.answer_text,
                answer: fallback,
                isStreaming: false,
                isServiceError: true,
              }
            : message,
        ),
      );
      finishAgentAnswer(agentMessageId, fallback.answer_text);
    }
  };

  const copyAnswer = async (message: ChatMessage) => {
    if (!message.text) return;
    await navigator.clipboard.writeText(message.text);
    setCopiedMessageId(message.id);
    window.setTimeout(() => setCopiedMessageId(null), 1400);
  };

  const latestUserQuestion = [...messages]
    .reverse()
    .find((message) => message.role === "user")?.text;

  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-border px-5 py-4">
        <SectionHeader
          title="Ask Governance Agent"
          sub="Evidence-backed governance Q&A"
          right={<EvidenceBadge />}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Select value={selectedProjectId} onValueChange={setSelectedProjectId}>
            <SelectTrigger className="h-9 w-full shadow-none sm:w-72">
              <SelectValue placeholder="Portfolio" />
            </SelectTrigger>
            <SelectContent data-governance-select-content>
              <SelectItem value={ALL_PROJECTS_VALUE}>Portfolio</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project.value} value={project.value}>
                  {project.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {messages.length > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 gap-1.5 text-xs shadow-none"
              disabled={askMutation.isPending}
              onClick={() => {
                setMessages([]);
                setSelectedAgentMessageId(null);
                setAnimatingMessageId(null);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear conversation
            </Button>
          )}
        </div>
      </div>

      <div className="grid min-h-[560px] gap-0 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-h-0 flex-col">
          <div className="min-h-0 flex-1 p-5">
            <div
              ref={chatScrollRef}
              className="h-[430px] space-y-4 overflow-y-auto rounded-md bg-secondary/35 p-4 text-xs"
            >
              {messages.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center text-center">
                  <div className="rounded-full border border-[color:var(--brand)]/20 bg-[color:var(--brand)]/8 p-3 text-[color:var(--brand)]">
                    <Bot className="h-7 w-7" />
                  </div>
                  <p className="mt-3 text-sm font-medium">Ask a governance question</p>
                  <p className="mt-1 max-w-sm text-[11px] leading-4 text-muted-foreground">
                    Answers use governance records and approved source-agent evidence.
                  </p>
                  <div className="mt-5 flex max-w-xl flex-wrap justify-center gap-2">
                    {GOVERNANCE_SUGGESTIONS.map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        className="rounded-full border border-border bg-card px-3 py-1.5 text-[11px] text-muted-foreground transition-colors hover:border-[color:var(--brand)]/40 hover:text-foreground"
                        onClick={() => void send(suggestion)}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((message) => {
                  const isAgent = message.role === "agent";
                  const isSelected = selectedAgentMessageId === message.id;
                  const isAnimating = animatingMessageId === message.id;
                  const answer = message.answer;
                  return (
                    <div
                      key={message.id}
                      className={cn(
                        "flex",
                        message.role === "user" ? "justify-end" : "justify-start",
                      )}
                    >
                      <button
                        type="button"
                        className={cn(
                          "max-w-[86%] rounded-md border bg-card px-3 py-3 text-left transition-colors",
                          isAgent
                            ? "border-border/70"
                            : "border-[color:var(--brand)]/20 bg-[color:var(--brand)]/5",
                          isAgent && isSelected && "ring-1 ring-[color:var(--brand)]/35",
                        )}
                        onClick={() => isAgent && setSelectedAgentMessageId(message.id)}
                      >
                        <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase text-muted-foreground">
                          <span>{message.role === "user" ? "You" : "Governance Agent"}</span>
                          {isAgent && answer && (
                            <>
                              <StatusPill status={confidenceStatus(answer.confidence_level)} />
                              {answer.insufficient_evidence && (
                                <span className="inline-flex items-center gap-1 text-[color:var(--warning)]">
                                  <TriangleAlert className="h-3 w-3" />
                                  Insufficient evidence
                                </span>
                              )}
                            </>
                          )}
                        </div>
                        {message.isStreaming ? (
                          <TypingIndicator className="text-muted-foreground" />
                        ) : isAnimating ? (
                          <TypewriterText
                            text={message.text}
                            className="whitespace-pre-wrap leading-5"
                            onComplete={() => setAnimatingMessageId(null)}
                          />
                        ) : (
                          <p
                            className={cn(
                              "whitespace-pre-wrap leading-5",
                              message.isServiceError && "text-foreground",
                            )}
                          >
                            {message.text}
                          </p>
                        )}
                        {isAgent && !message.isStreaming && answer && (
                          <div className="mt-2.5 border-t border-border/50 pt-2">
                            <div className="mb-1.5 flex flex-wrap gap-1.5">
                              {answer.evidence_links.slice(0, 5).map((link, index) => (
                                <span
                                  key={`${link.source_table}-${link.source_row_id}-${index}`}
                                  className="rounded-full border border-border bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground"
                                >
                                  [{index + 1}] {sourceLabel(link.source_table)}
                                </span>
                              ))}
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                              <button
                                type="button"
                                className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void copyAnswer(message);
                                }}
                              >
                                {copiedMessageId === message.id ? (
                                  <Check className="h-3 w-3" />
                                ) : (
                                  <Copy className="h-3 w-3" />
                                )}
                                {copiedMessageId === message.id ? "Copied" : "Copy"}
                              </button>
                              {latestUserQuestion && message.id === selectedAgentMessage?.id && (
                                <button
                                  type="button"
                                  className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground hover:bg-secondary/70 hover:text-foreground disabled:opacity-50"
                                  disabled={askMutation.isPending}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void send(latestUserQuestion);
                                  }}
                                >
                                  <RefreshCw className="h-3 w-3" />
                                  Regenerate
                                </button>
                              )}
                            </div>
                          </div>
                        )}
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="border-t border-border p-5">
            <form
              className="flex items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                void send(input);
              }}
            >
              <Textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask about governance risks, overdue actions, scope changes, or leadership attention..."
                className="h-10 min-h-10 resize-none overflow-hidden bg-card py-2 shadow-none"
                disabled={askMutation.isPending}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send(input);
                  }
                }}
              />
              <Button type="submit" className="h-10 shadow-none" disabled={askMutation.isPending}>
                <Send className="h-4 w-4" />
                {askMutation.isPending ? "Asking" : "Ask"}
              </Button>
            </form>
          </div>
        </div>

        <aside className="border-t border-border bg-elevated p-4 lg:border-l lg:border-t-0">
          <div className="mb-3 flex items-start justify-between gap-2">
            <div>
              <p className="text-xs font-semibold">Evidence</p>
              <p className="text-[11px] text-muted-foreground">
                {selectedAnswer
                  ? `${selectedAnswer.evidence_links.length} linked records`
                  : "No answer selected"}
              </p>
            </div>
            {selectedAnswer?.confidence_level && (
              <div className="rounded-md border border-border bg-card px-2 py-1 text-right">
                <div className="text-[10px] uppercase text-muted-foreground">Confidence</div>
                <div className="text-xs font-semibold">
                  {confidencePercent(selectedAnswer.confidence_level)}%
                </div>
              </div>
            )}
          </div>

          {selectedAnswer?.source_agents_used?.length ? (
            <div className="mb-3 flex flex-wrap gap-1.5">
              {selectedAnswer.source_agents_used.map((source) => (
                <span
                  key={source}
                  className="rounded-full border border-border bg-card px-2 py-0.5 text-[10px] text-muted-foreground"
                >
                  {source}
                </span>
              ))}
            </div>
          ) : null}

          <div className="max-h-[500px] space-y-3 overflow-y-auto">
            {Object.entries(evidenceGroups).length === 0 ? (
              <p className="rounded-md border border-border bg-card p-3 text-xs text-muted-foreground">
                Select an answer to inspect its evidence links.
              </p>
            ) : (
              Object.entries(evidenceGroups).map(([group, links]) => (
                <div key={group}>
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {group}
                  </div>
                  <div className="space-y-1.5">
                    {links.map((link) => (
                      <div
                        key={`${link.source_table}-${link.source_row_id}`}
                        className="rounded-md border border-border bg-card p-2"
                      >
                        <div className="text-[11px] font-medium">{link.source_table}</div>
                        <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                          {link.description}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>
      </div>
    </Card>
  );
}

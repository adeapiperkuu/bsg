import { useState } from "react";
import { AiBadge, EvidenceBadge } from "@/components/bsg/widgets";
import { useAgentQuery } from "@/hooks/useAgentQuery";

type Props = {
  projectId: string | undefined;
};

type Message = { role: "user" | "ai"; text: string; confidence?: number };

export function AgentQueryBox({ projectId }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const mutation = useAgentQuery(projectId);

  const send = async (text: string) => {
    if (!text.trim() || !projectId) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    try {
      const result = await mutation.mutateAsync(text);
      setMessages((m) => [
        ...m,
        {
          role: "ai",
          text: result.answer_text,
          confidence: result.evidence_links.length > 0 ? 85 : 50,
        },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "ai", text: "Unable to reach the quality agent. Check your connection and try again." },
      ]);
    }
  };

  return (
    <div className="rounded-md border border-border bg-elevated p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-medium">Ask Quality Intelligence</div>
        <EvidenceBadge />
      </div>
      {!projectId && (
        <p className="mb-3 text-xs text-muted-foreground">Select a project to ask quality questions.</p>
      )}
      <div className="mb-3 max-h-48 space-y-2 overflow-y-auto text-xs">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`rounded-md p-2 ${msg.role === "user" ? "bg-card ml-8" : "bg-card mr-8"}`}
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="font-medium text-muted-foreground">{msg.role === "user" ? "You" : "Agent"}</span>
              {msg.role === "ai" && msg.confidence != null && <AiBadge confidence={msg.confidence} />}
            </div>
            <p className="whitespace-pre-wrap leading-5">{msg.text}</p>
          </div>
        ))}
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Why is accuracy dropping this week?"
          disabled={!projectId || mutation.isPending}
          className="flex-1 rounded border border-border bg-card px-3 py-2 text-xs outline-none"
        />
        <button
          type="submit"
          disabled={!projectId || mutation.isPending}
          className="rounded bg-[color:var(--brand)] px-3 py-2 text-xs font-medium text-[color:var(--brand-foreground)] disabled:opacity-50"
        >
          {mutation.isPending ? "…" : "Ask"}
        </button>
      </form>
    </div>
  );
}

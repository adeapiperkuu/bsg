import type { ReactNode } from "react";
import { Bot } from "lucide-react";
import { TypewriterText } from "@/components/knowledge/TypewriterText";
import { cn } from "@/lib/utils";
import type { DeliveryChatMessage, DeliveryChatSource } from "@/types/delivery-chat";

type Props = {
  message: DeliveryChatMessage;
  isAnimating: boolean;
  onAnimationProgress?: () => void;
  onAnimationComplete?: () => void;
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  risk: "Risk",
  bottleneck: "Bottleneck",
  milestone: "Milestone",
  throughput: "Throughput",
  project: "Project",
  evidence: "Evidence",
};

function renderInline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <span key={index}>{part}</span>;
  });
}

function DeliveryMarkdownContent({ content, className }: { content: string; className?: string }) {
  const lines = content.split("\n");
  const blocks: ReactNode[] = [];
  let listItems: string[] = [];
  let listOrdered = false;

  const flushList = () => {
    if (listItems.length === 0) return;
    const ListTag = listOrdered ? "ol" : "ul";
    blocks.push(
      <ListTag
        key={`list-${blocks.length}`}
        className={cn(
          "my-2 space-y-1 pl-4 text-[11px] leading-4",
          listOrdered ? "list-decimal" : "list-disc",
        )}
      >
        {listItems.map((item, index) => (
          <li key={index}>{renderInline(item)}</li>
        ))}
      </ListTag>,
    );
    listItems = [];
    listOrdered = false;
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    const bulletMatch = trimmed.match(/^[-*]\s+(.+)$/);
    const headingMatch = trimmed.match(/^#{1,3}\s+(.+)$/);

    if (orderedMatch) {
      if (listItems.length > 0 && !listOrdered) flushList();
      listOrdered = true;
      listItems.push(orderedMatch[1]);
      continue;
    }

    if (bulletMatch) {
      if (listItems.length > 0 && listOrdered) flushList();
      listItems.push(bulletMatch[1]);
      continue;
    }

    flushList();

    if (headingMatch) {
      blocks.push(
        <div
          key={`heading-${blocks.length}`}
          className="mt-2.5 first:mt-0 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
        >
          {renderInline(headingMatch[1])}
        </div>,
      );
      continue;
    }

    if (trimmed.startsWith("**") && trimmed.endsWith("**")) {
      blocks.push(
        <div
          key={`bold-${blocks.length}`}
          className="mt-2.5 first:mt-0 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
        >
          {trimmed.slice(2, -2)}
        </div>,
      );
      continue;
    }

    blocks.push(
      <p key={`p-${blocks.length}`} className="text-[11px] leading-5 text-foreground">
        {renderInline(trimmed)}
      </p>,
    );
  }

  flushList();

  return <div className={cn("space-y-1", className)}>{blocks}</div>;
}

function DeliverySourceCard({ source }: { source: DeliveryChatSource }) {
  const typeLabel = SOURCE_TYPE_LABELS[source.type] ?? source.type;

  return (
    <span
      className="inline-flex max-w-full flex-col rounded-md border border-border/70 bg-secondary/50 px-2 py-1 text-left text-[10px] text-foreground"
      title={source.description ?? undefined}
    >
      <span className="truncate font-medium">{source.title}</span>
      <span className="text-muted-foreground">{typeLabel}</span>
    </span>
  );
}

export function DeliveryMessage({
  message,
  isAnimating,
  onAnimationProgress,
  onAnimationComplete,
}: Props) {
  const showAgentDetails = message.role === "agent" && !isAnimating;

  return (
    <div
      className={cn(
        "flex gap-3",
        message.role === "user" ? "justify-end" : "justify-start",
      )}
    >
      {message.role === "agent" && (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground">
          <Bot className="h-3.5 w-3.5" />
        </div>
      )}
      <div
        className={cn(
          "max-w-[88%] rounded-md px-3 py-3",
          message.role === "user"
            ? "bg-[color:var(--brand)] text-[color:var(--brand-foreground)]"
            : "bg-card",
          message.error && "border border-[color:var(--danger)]/30",
        )}
      >
        <div
          className={cn(
            "mb-1 text-[10px] font-semibold uppercase tracking-wider",
            message.role === "user" ? "text-white/70" : "text-muted-foreground",
          )}
        >
          {message.role === "user" ? "You" : "Delivery Agent"}
        </div>

        {isAnimating ? (
          <TypewriterText
            text={message.text}
            className="text-[11px] leading-5"
            onProgress={onAnimationProgress}
            onComplete={onAnimationComplete}
          />
        ) : message.role === "agent" ? (
          <DeliveryMarkdownContent content={message.text} />
        ) : (
          <p className="text-[11px] leading-5">{message.text}</p>
        )}

        {showAgentDetails && message.sources && message.sources.length > 0 && (
          <div className="mt-2.5 border-t border-border/50 pt-2">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Evidence
            </div>
            <div className="flex flex-wrap gap-1.5">
              {message.sources.map((source) => (
                <DeliverySourceCard key={`${source.type}-${source.title}`} source={source} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

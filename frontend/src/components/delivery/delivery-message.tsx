import { Bot } from "lucide-react";
import { TypewriterText } from "@/components/knowledge/TypewriterText";
import { DeliveryMarkdown } from "@/components/delivery/delivery-markdown";
import { deliveryMarkdownPreview } from "@/components/delivery/delivery-markdown-utils";
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

function DeliverySourceCard({ source }: { source: DeliveryChatSource }) {
  const typeLabel = SOURCE_TYPE_LABELS[source.type] ?? source.type;

  return (
    <span
      className="inline-flex max-w-full flex-col rounded-md border border-border/70 bg-secondary/50 px-2 py-1.5 text-left text-[10px] text-foreground"
      title={source.description ?? undefined}
    >
      <span className="truncate font-medium">{source.title}</span>
      <span className="text-muted-foreground">{typeLabel}</span>
      {source.description ? (
        <span className="mt-0.5 line-clamp-2 text-[9px] leading-3 text-muted-foreground">
          {source.description}
        </span>
      ) : null}
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
    <div className={cn("flex gap-3", message.role === "user" ? "justify-end" : "justify-start")}>
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
            text={deliveryMarkdownPreview(message.text)}
            className="text-[11px] leading-5 text-foreground"
            onProgress={onAnimationProgress}
            onComplete={onAnimationComplete}
          />
        ) : message.role === "agent" ? (
          <DeliveryMarkdown content={message.text} />
        ) : (
          <p className="text-[11px] leading-5">{message.text}</p>
        )}

        {showAgentDetails && message.sources && message.sources.length > 0 && (
          <div className="mt-3 border-t border-border/50 pt-2.5">
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Supporting evidence
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

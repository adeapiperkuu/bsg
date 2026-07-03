export type DeliveryChatRole = "user" | "agent";

// Must match backend `delivery_chat_max_message_length` (backend/app/core/config.py),
// enforced again server-side in DeliveryChatCreate — this is a UX convenience, not the
// source of truth.
export const DELIVERY_CHAT_MAX_MESSAGE_LENGTH = 2000;

export interface DeliveryChatSource {
  title: string;
  type: string;
  id?: string | null;
  description?: string | null;
}

export interface DeliveryChatRequest {
  message: string;
  project_id?: string | null;
  conversation_id?: string | null;
}

export interface DeliveryChatResponse {
  answer: string;
  sources: DeliveryChatSource[];
  conversation_id: string;
}

export interface DeliveryChatTurn {
  id: string;
  query_text: string;
  answer_text: string;
  created_at: string;
  sources: DeliveryChatSource[];
}

export interface DeliveryChatConversation {
  conversation_id: string;
  project_id: string | null;
  turns: DeliveryChatTurn[];
}

export interface DeliveryChatMessage {
  id: string;
  role: DeliveryChatRole;
  text: string;
  sources?: DeliveryChatSource[];
  error?: boolean;
  /** True while an agent message is still receiving streamed tokens. */
  streaming?: boolean;
}

export const DELIVERY_SUGGESTED_PROMPTS = [
  "Which projects are at risk?",
  "Why did throughput decline?",
  "What's blocking delivery?",
  "Which milestones are likely to slip?",
  "What delivery risks need attention this week?",
] as const;

const DELIVERY_THEME_SUGGESTIONS: Array<{ keywords: string[]; suggestions: string[] }> = [
  {
    keywords: ["risk", "at risk", "risky"],
    suggestions: [
      "Which milestone is most at risk?",
      "What is driving confidence down?",
      "Which teams are most affected?",
      "What should be escalated?",
    ],
  },
  {
    keywords: ["bottleneck", "blocking", "blocked", "blocker", "impediment"],
    suggestions: [
      "Which bottlenecks need attention?",
      "Who owns resolving these blockers?",
      "What should be escalated?",
      "How long have these blockers been open?",
    ],
  },
  {
    keywords: ["milestone", "deadline", "slip", "schedule", "timeline"],
    suggestions: [
      "Which milestones are likely to slip?",
      "What is the critical path?",
      "Which teams are behind schedule?",
      "What recovery actions are available?",
    ],
  },
  {
    keywords: ["throughput", "velocity", "pace", "delivery rate"],
    suggestions: [
      "Why did throughput decline?",
      "How does this compare to previous sprints?",
      "Which teams have the lowest throughput?",
      "What is affecting delivery pace?",
    ],
  },
  {
    keywords: ["confidence", "health", "score"],
    suggestions: [
      "What is driving the confidence score?",
      "Which areas need the most support?",
      "How has confidence changed over time?",
      "What would improve confidence?",
    ],
  },
  {
    keywords: ["escalat", "critical", "urgent", "priority"],
    suggestions: [
      "What should be escalated immediately?",
      "Which issues are most critical?",
      "What actions should be taken first?",
      "Who needs to be informed?",
    ],
  },
  {
    keywords: ["project", "team", "initiative"],
    suggestions: [
      "Which projects are at risk?",
      "How are teams performing overall?",
      "What's blocking delivery?",
      "Which initiatives need attention?",
    ],
  },
];

const SUGGESTION_FALLBACKS = [
  "Which projects are at risk?",
  "What's blocking delivery?",
  "Which milestones are likely to slip?",
  "What delivery risks need attention this week?",
];

export function generateDeliverySuggestions(responseText: string): string[] {
  const lower = responseText.toLowerCase();
  const seen = new Set<string>();
  const result: string[] = [];

  for (const theme of DELIVERY_THEME_SUGGESTIONS) {
    if (theme.keywords.some((kw) => lower.includes(kw))) {
      for (const s of theme.suggestions) {
        if (!seen.has(s) && result.length < 5) {
          seen.add(s);
          result.push(s);
        }
      }
    }
    if (result.length >= 5) break;
  }

  for (const s of SUGGESTION_FALLBACKS) {
    if (result.length >= 3) break;
    if (!seen.has(s)) {
      seen.add(s);
      result.push(s);
    }
  }

  return result.slice(0, 5);
}

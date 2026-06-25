export type DeliveryChatRole = "user" | "agent";

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

export interface DeliveryChatMessage {
  id: string;
  role: DeliveryChatRole;
  text: string;
  sources?: DeliveryChatSource[];
  error?: boolean;
}

export const DELIVERY_SUGGESTED_PROMPTS = [
  "Which projects are at risk?",
  "Why did throughput decline?",
  "What's blocking delivery?",
  "Which milestones are likely to slip?",
  "What delivery risks need attention this week?",
] as const;

import type { WorkforceChatSession } from "./types";

export function createMessageId(): string {
  return crypto.randomUUID();
}

export function createSession(projectId: string | null): WorkforceChatSession {
  const now = new Date().toISOString();
  return {
    id: createMessageId(),
    projectId,
    title: "New chat",
    messages: [],
    createdAt: now,
    updatedAt: now,
  };
}

export function sessionPreviewTitle(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return "New chat";
  return trimmed.length > 42 ? `${trimmed.slice(0, 42)}…` : trimmed;
}

export function formatSessionTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

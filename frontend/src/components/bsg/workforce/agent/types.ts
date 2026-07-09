import type { AgentQueryRead } from "@/types/workforce";

export type WorkforceChatMessage = {
  id: string;
  role: "user" | "agent";
  text: string;
  answer?: AgentQueryRead;
  error?: boolean;
};

export type WorkforceChatSession = {
  id: string;
  projectId: string | null;
  title: string;
  messages: WorkforceChatMessage[];
  createdAt: string;
  updatedAt: string;
};

import { useMutation } from "@tanstack/react-query";
import { postAgentQuery, type AgentQueryRead } from "@/lib/api";

export function useAgentQuery(projectId: string | undefined) {
  return useMutation({
    mutationFn: (queryText: string) =>
      postAgentQuery({
        agent_name: "quality_intelligence_agent",
        project_id: projectId,
        query_text: queryText,
      }),
  });
}

export type { AgentQueryRead };

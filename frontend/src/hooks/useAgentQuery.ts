import { useMutation } from "@tanstack/react-query";
import { postAgentQuery } from "@/lib/api";
import type { AgentQueryRead } from "@/types/workforce";

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

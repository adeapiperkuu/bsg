import { useCallback, useState } from "react";
import { postAgentQuery, streamAgentQuery } from "@/lib/api";
import type { AgentQueryRead } from "@/types/workforce";

export type AgentQueryPhase =
  | "idle"
  | "gathering_evidence"
  | "reasoning"
  | "writing"
  | "done"
  | "error";

/**
 * Ask the Quality Intelligence agent, preferring the SSE streaming endpoint
 * (status updates from ~0s, then the answer streamed token-by-token once
 * synthesis begins) with a transparent fallback to the non-streaming
 * endpoint if the stream fails to establish or errors mid-flight.
 *
 * The returned promise always resolves to the same AgentQueryRead shape
 * postAgentQuery used to return directly, so existing callers only need to
 * additionally watch `phase` / `streamingText` for live progress.
 */
export function useAgentQuery(projectId: string | undefined) {
  const [isPending, setIsPending] = useState(false);
  const [phase, setPhase] = useState<AgentQueryPhase>("idle");
  const [streamingText, setStreamingText] = useState("");

  const mutateAsync = useCallback(
    async (queryText: string): Promise<AgentQueryRead> => {
      if (!projectId) {
        throw new Error("A project must be selected to ask the quality agent.");
      }

      setIsPending(true);
      setPhase("gathering_evidence");
      setStreamingText("");

      try {
        let result: AgentQueryRead | null = null;
        let streamFailed = false;
        let streamedAnswer = "";

        try {
          for await (const event of streamAgentQuery({
            agent_name: "quality_intelligence_agent",
            project_id: projectId,
            query_text: queryText,
          })) {
            if (event.type === "status") {
              setPhase(event.phase);
            } else if (event.type === "delta") {
              streamedAnswer += event.text;
              setStreamingText(streamedAnswer);
            } else if (event.type === "done") {
              result = event.data;
            } else if (event.type === "error") {
              streamFailed = true;
              break;
            }
          }
        } catch {
          // Network/stream failure (e.g. connection dropped mid-response) —
          // fall back below rather than surfacing this to the caller.
          streamFailed = true;
        }

        if (!result || streamFailed) {
          result = await postAgentQuery({
            agent_name: "quality_intelligence_agent",
            project_id: projectId,
            query_text: queryText,
          });
        }

        setPhase("done");
        return result;
      } catch (err) {
        setPhase("error");
        throw err;
      } finally {
        setIsPending(false);
        setStreamingText("");
        setPhase("idle");
      }
    },
    [projectId],
  );

  return { mutateAsync, isPending, phase, streamingText };
}

export type { AgentQueryRead };

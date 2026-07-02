import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import {
  knowledgeDocumentQueryOptions,
  knowledgeDocumentVersionsQueryOptions,
  useKnowledgeSessionReady,
} from "@/lib/queries/knowledge";
import type { KnowledgeDocument } from "@/lib/knowledge-mappers";
import type { KnowledgeDocumentVersionApi } from "@/types/knowledge";

export type DocumentDetailTab = "preview" | "metadata" | "chunks" | "versions" | "evidence";

const DETAIL_TABS = new Set<DocumentDetailTab>(["preview", "metadata", "chunks", "evidence"]);

export function useDocumentTabLoader(options: {
  documentId: string | null;
  isOpen: boolean;
  enabled: boolean;
  activeTab: DocumentDetailTab;
  onDocumentLoaded: (document: KnowledgeDocument) => void;
  onVersionsLoaded: (versions: KnowledgeDocumentVersionApi[]) => void;
}) {
  const sessionReady = useKnowledgeSessionReady();
  const documentId = options.documentId ?? "";
  const detailEnabled =
    sessionReady &&
    options.isOpen &&
    options.enabled &&
    Boolean(options.documentId) &&
    DETAIL_TABS.has(options.activeTab);
  const versionsEnabled =
    sessionReady &&
    options.isOpen &&
    options.enabled &&
    Boolean(options.documentId) &&
    options.activeTab === "versions";

  const detailQuery = useQuery({
    ...knowledgeDocumentQueryOptions(documentId),
    enabled: detailEnabled,
    placeholderData: keepPreviousData,
  });

  const versionsQuery = useQuery({
    ...knowledgeDocumentVersionsQueryOptions(documentId),
    enabled: versionsEnabled,
    placeholderData: keepPreviousData,
  });

  useEffect(() => {
    if (detailQuery.data) {
      options.onDocumentLoaded(detailQuery.data);
    }
  }, [detailQuery.data, options.onDocumentLoaded]);

  useEffect(() => {
    if (versionsQuery.data) {
      options.onVersionsLoaded(versionsQuery.data);
    }
  }, [versionsQuery.data, options.onVersionsLoaded]);

  return {
    loadingDetail: detailQuery.isFetching && !detailQuery.data,
    loadingVersions: versionsQuery.isFetching && !versionsQuery.data?.length,
  };
}

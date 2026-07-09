import { createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import {
  askKnowledgeAgent,
  compareKnowledgeDocumentVersions,
  downloadKnowledgeDocumentFile,
  getKnowledgeConversation,
  streamKnowledgeAsk,
  submitKnowledgeFeedback,
} from "@/lib/api";
import { queryKeys } from "@/lib/queries/keys";
import {
  invalidateKnowledgeAgentQueries,
  patchKnowledgeDocumentsCache,
  useCreateKnowledgeFolderMutation,
  useDeleteKnowledgeDocumentMutation,
  useKnowledgeBootstrapQuery,
  useKnowledgeDocumentsQuery,
  useKnowledgeLibraryHealthQuery,
  useKnowledgeRetrievalSettingsQuery,
  useReindexKnowledgeDocumentMutation,
  useResolveKnowledgeGapMutation,
  useUpdateKnowledgeDocumentMutation,
  useUpdateKnowledgeRetrievalSettingsMutation,
  useUploadKnowledgeDocumentMutation,
} from "@/lib/queries/knowledge";
import { KnowledgeHistoryPopover } from "@/components/knowledge/KnowledgeHistoryPopover";
import { DocBadge, Field, MetaRow, QualityScoreBadge } from "@/components/knowledge/knowledge-ui";
import { TypewriterText } from "@/components/knowledge/TypewriterText";
import { TypingIndicator } from "@/components/knowledge/TypingIndicator";
import { useDocumentTabLoader, type DocumentDetailTab } from "@/hooks/useDocumentTabLoader";
import { useLazyWhenVisible } from "@/hooks/useLazyWhenVisible";
import { useAuthStore } from "@/stores/useAuthStore";
import {
  documentFromApi,
  documentSummaryFromApi,
  documentToApiPatch,
  isRetrievalReady,
  uploadFormToApi,
  type DocumentStatus,
  type KnowledgeDocument,
  type SourceType,
  type Visibility,
  type WorkflowState,
} from "@/lib/knowledge-mappers";
import type {
  KnowledgeAskResponseApi,
  KnowledgeConversationSummaryApi,
  KnowledgeConversationTurnApi,
  KnowledgeDocumentVersionApi,
  KnowledgeFolderKind,
  KnowledgeGapApi,
  KnowledgeGapTodoApi,
  KnowledgeLibraryHealthApi,
  KnowledgeProcessingStatusApi,
  KnowledgeRetrievalSettingsApi,
  KnowledgeRetrievalDebugApi,
  KnowledgeStructuredAnswerApi,
  KnowledgeVersionCompareApi,
} from "@/types/knowledge";
import {
  AlertTriangle,
  Copy,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  FileText,
  Filter,
  Folder,
  History,
  Loader2,
  Plus,
  Send,
  RefreshCw,
  Search,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Upload,
} from "lucide-react";

export const Route = createFileRoute("/knowledge")({ component: KnowledgePage });

const LazyKnowledgeDocumentTabPanels = lazy(() =>
  import("@/components/knowledge/KnowledgeDocumentTabPanels").then((module) => ({
    default: module.KnowledgeDocumentTabPanels,
  })),
);

function DocumentTabFallback() {
  return (
    <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      Loading panel...
    </div>
  );
}

type UploadState = "idle" | "uploading" | "success" | "error";
type SortMode = "recent" | "title" | "approved" | "indexed";
type HealthFilter = "all" | "ready" | "needs_approval" | "indexing" | "archived" | "expired" | "needs_reindex";
type ChatMessage = {
  id: string;
  role: "user" | "agent";
  text: string;
  next_step?: string;
  confidence_score?: number;
  confidence_reasons?: string[];
  structured_answer?: KnowledgeStructuredAnswerApi | null;
  knowledge_gap?: KnowledgeGapApi | null;
  retrieval_debug?: KnowledgeRetrievalDebugApi | null;
  regenerationSummary?: string;
  query_id?: string | null;
  feedback?: "up" | "down";
  feedbackComment?: string;
  isServiceError?: boolean;
  isStreaming?: boolean;
  streamPhase?: "searching" | "reading" | "generating";
  wasStreamed?: boolean;
  isHistorical?: boolean;
  retryQuestion?: string;
  detailsExpanded?: boolean;
};
type LibraryFolder = { id: string; kind: KnowledgeFolderKind; name: string };

const workflowStates: WorkflowState[] = [
  "Needs review",
  "Approved",
  "Expired",
  "Needs re-index",
  "Archived",
];

const sourceTypes: SourceType[] = [
  "SOP",
  "Guide",
  "Training Document",
  "Project Charter",
  "Escalation Note",
  "Lesson Learned",
];
const visibilities: Visibility[] = ["Internal-only", "Leadership-only", "Client-safe"];
const statuses: DocumentStatus[] = ["Draft", "Approved", "Archived"];
const acceptedExtensions = [".pdf", ".docx", ".txt", ".md", ".csv"];
const folderPreviewLimit = 6;
const SUGGESTED_QUESTION_LIMIT = 4;
const FALLBACK_SUGGESTED_QUESTIONS = [
  "When should a quality escalation be triggered?",
  "What are the onboarding steps before production launch?",
  "What actions improved quality in past projects?",
];
const FOLDER_SUGGESTIONS: Partial<Record<KnowledgeFolderKind, string>> = {
  sops: "What quality and escalation SOPs are available?",
  guides: "Ask about Guides — what onboarding steps are documented?",
  histories: "Ask about Histories — what lessons learned are captured?",
};
const TYPEWRITER_MAX_CHARS = 4000;
const STREAM_PHASE_LABELS: Record<NonNullable<ChatMessage["streamPhase"]>, string> = {
  searching: "Searching sources…",
  reading: "Reading documents…",
  generating: "Generating answer…",
};
const LOW_CONFIDENCE_THRESHOLD = 0.5;
const NO_KNOWLEDGE_ANSWER =
  "I could not find this information in the uploaded knowledge base.";
const KNOWLEDGE_CHAT_STORAGE_PREFIX = "bsg:knowledge-chat";
const KNOWLEDGE_LIBRARY_SNAPSHOT_KEY = "bsg:knowledge-library-snapshot";
const KNOWLEDGE_LIBRARY_SNAPSHOT_TTL_MS = 30 * 60 * 1000;
const CHAT_SCROLL_THRESHOLD_PX = 80;
const LIBRARY_DEBOUNCE_MS = 120;

type KnowledgeChatSession = {
  conversationId: string | null;
  messages: ChatMessage[];
};

type KnowledgeLibrarySnapshot = {
  documents: KnowledgeDocument[];
  folders: LibraryFolder[];
  libraryHealth: KnowledgeLibraryHealthApi;
  savedAt: number;
};

function createChatMessageId() {
  return crypto.randomUUID();
}

function useDebouncedValue<T>(value: T, delayMs: number) {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedValue(value), delayMs);
    return () => window.clearTimeout(timeout);
  }, [delayMs, value]);

  return debouncedValue;
}

function loadKnowledgeLibrarySnapshot(): KnowledgeLibrarySnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KNOWLEDGE_LIBRARY_SNAPSHOT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as KnowledgeLibrarySnapshot;
    if (!Array.isArray(parsed.documents) || !Array.isArray(parsed.folders)) return null;
    if (!parsed.libraryHealth || typeof parsed.savedAt !== "number") return null;
    if (Date.now() - parsed.savedAt > KNOWLEDGE_LIBRARY_SNAPSHOT_TTL_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveKnowledgeLibrarySnapshot(snapshot: KnowledgeLibrarySnapshot) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KNOWLEDGE_LIBRARY_SNAPSHOT_KEY, JSON.stringify(snapshot));
  } catch {
    // Ignore storage quota and private browsing failures.
  }
}

function getKnowledgeLibrarySnapshotSignature(
  documents: KnowledgeDocument[],
  folders: LibraryFolder[],
  libraryHealth: KnowledgeLibraryHealthApi,
) {
  return JSON.stringify({
    documents: documents.map((document) => [
      document.id,
      document.title,
      document.folderId,
      document.version,
      document.status,
      document.workflowState,
      document.processingStatus,
      document.indexed,
      document.indexing,
      document.effectiveDate,
    ]),
    folders: folders.map((folder) => [folder.id, folder.kind, folder.name]),
    health: [
      libraryHealth.ready_count,
      libraryHealth.needs_review_count,
      libraryHealth.expired_count,
      libraryHealth.needs_reindex_count,
      libraryHealth.indexing_count,
      libraryHealth.draft_count,
      libraryHealth.archived_count,
      ...libraryHealth.open_gaps.map((gap) => gap.id),
    ],
  });
}

function normalizeChatMessage(value: unknown): ChatMessage | null {
  if (!value || typeof value !== "object") return null;
  const msg = value as ChatMessage;
  if (msg.role !== "user" && msg.role !== "agent") return null;
  if (typeof msg.text !== "string") return null;
  return { ...msg, id: msg.id ?? createChatMessageId() };
}

function createUserMessage(text: string): ChatMessage {
  return { id: createChatMessageId(), role: "user", text };
}

function getKnowledgeChatStorageKey(userId: string) {
  return `${KNOWLEDGE_CHAT_STORAGE_PREFIX}:${userId}`;
}

function isChatMessage(value: unknown): value is ChatMessage {
  return normalizeChatMessage(value) !== null;
}

function loadKnowledgeChatSession(userId: string): KnowledgeChatSession | null {
  try {
    const raw = sessionStorage.getItem(getKnowledgeChatStorageKey(userId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as KnowledgeChatSession;
    if (!Array.isArray(parsed.messages)) return null;
    const messages = parsed.messages
      .map(normalizeChatMessage)
      .filter((message): message is ChatMessage => message !== null);
    if (messages.length !== parsed.messages.length) return null;
    const conversationId =
      typeof (parsed as KnowledgeChatSession).conversationId === "string"
        ? (parsed as KnowledgeChatSession).conversationId
        : null;
    return { messages, conversationId };
  } catch {
    return null;
  }
}

function saveKnowledgeChatSession(userId: string, session: KnowledgeChatSession) {
  try {
    sessionStorage.setItem(getKnowledgeChatStorageKey(userId), JSON.stringify(session));
  } catch {
    // ignore quota errors or private browsing
  }
}

function clearKnowledgeChatSession(userId: string) {
  try {
    sessionStorage.removeItem(getKnowledgeChatStorageKey(userId));
  } catch {
    // ignore
  }
}

function buildSuggestedQuestions(
  documents: KnowledgeDocument[],
  folders: LibraryFolder[],
  limit = SUGGESTED_QUESTION_LIMIT,
): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  const add = (question: string) => {
    const text = question.trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key) || result.length >= limit) return;
    seen.add(key);
    result.push(text);
  };

  const readyDocs = documents.filter(isRetrievalReady);

  for (const doc of readyDocs.filter((item) => item.sourceType === "SOP").slice(0, 2)) {
    add(`What does the "${doc.title}" SOP cover?`);
  }

  for (const folder of folders) {
    if (result.length >= limit) break;
    const hasReady = readyDocs.some((doc) => doc.folderId === folder.id);
    if (!hasReady) continue;
    const template = FOLDER_SUGGESTIONS[folder.kind];
    if (template) add(template);
    else if (folder.kind === "custom") add(`Ask about ${folder.name} — what's documented there?`);
  }

  for (const fallback of FALLBACK_SUGGESTED_QUESTIONS) {
    if (result.length >= limit) break;
    add(fallback);
  }

  return result.slice(0, limit);
}

function formatRetrievalScopeLabel(settings: KnowledgeRetrievalSettingsApi | null): string | null {
  if (!settings) return null;
  const parts: string[] = [];
  if (settings.project) parts.push(`Project: ${settings.project}`);
  if (settings.department) parts.push(`Department: ${settings.department}`);
  if (!settings.include_histories) parts.push("Histories off");
  if (parts.length === 0) return null;
  return parts.join(" / ");
}

const KNOWLEDGE_CONVERSATION_TURN_LIMIT = 6;

function buildConversationHistory(messages: ChatMessage[]) {
  return messages
    .filter((message) => !message.isServiceError)
    .slice(-KNOWLEDGE_CONVERSATION_TURN_LIMIT)
    .map((message) => ({
      role: message.role === "user" ? ("user" as const) : ("assistant" as const),
      content: message.text,
    }));
}

function findPrecedingUserQuestion(messages: ChatMessage[], agentMessageId: string): string | null {
  const agentIndex = messages.findIndex((message) => message.id === agentMessageId);
  if (agentIndex < 0) return null;
  for (let i = agentIndex - 1; i >= 0; i -= 1) {
    if (messages[i].role === "user") return messages[i].text;
  }
  return null;
}

function agentMessageFromResponse(
  response: KnowledgeAskResponseApi,
  options?: { isHistorical?: boolean },
): ChatMessage {
  return {
    id: createChatMessageId(),
    role: "agent",
    text: response.answer_text,
    next_step: response.next_step,
    confidence_score: response.confidence_score,
    confidence_reasons: response.confidence_reasons,
    structured_answer: response.structured_answer,
    knowledge_gap: response.knowledge_gap,
    retrieval_debug: response.retrieval_debug ?? null,
    query_id: response.query_id,
    isHistorical: options?.isHistorical ?? false,
    wasStreamed: options?.isHistorical ? false : undefined,
    detailsExpanded:
      (response.confidence_score ?? 1) < LOW_CONFIDENCE_THRESHOLD || !!response.knowledge_gap,
  };
}

function messagesFromConversation(turns: KnowledgeConversationTurnApi[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  for (const turn of turns) {
    messages.push(createUserMessage(turn.query_text));
    messages.push(agentMessageFromResponse(turn.answer, { isHistorical: true }));
  }
  return messages;
}

function inferAnswerMode(question: string): "internal" | "client_safe" {
  const lowered = question.toLowerCase();
  return /\b(client|customer|external|client-safe|customer-facing)\b/.test(lowered)
    ? "client_safe"
    : "internal";
}

function shouldAnimateAnswer(text: string) {
  return text.trim().length > 0 && text.length <= TYPEWRITER_MAX_CHARS;
}

function buildAgentDisplayText(
  message: Pick<ChatMessage, "text" | "structured_answer" | "next_step">,
): string {
  const direct = message.text?.trim();
  if (direct) return direct;
  const sa = message.structured_answer;
  if (sa) {
    const parts = [sa.policy, sa.steps, sa.owner, sa.evidence, sa.next_action]
      .map((part) => part?.trim())
      .filter(Boolean);
    if (parts.length > 0) return parts.join("\n\n");
  }
  const nextStep = message.next_step?.trim();
  if (nextStep) return nextStep;
  return "";
}

function resolveAgentAnswerText(
  message: Pick<ChatMessage, "text" | "structured_answer" | "next_step">,
  answerText?: string | null,
  options?: { useFallback?: boolean },
): string {
  const merged = {
    ...message,
    text: answerText?.trim() || message.text,
  };
  const display = buildAgentDisplayText(merged);
  if (display) return display;
  if (options?.useFallback === false) return "";
  return NO_KNOWLEDGE_ANSWER;
}

function isLowConfidenceMessage(message: ChatMessage) {
  return (message.confidence_score ?? 1) < LOW_CONFIDENCE_THRESHOLD;
}

function isMessageDetailsOpen(message: ChatMessage) {
  return message.detailsExpanded ?? (isLowConfidenceMessage(message) || !!message.knowledge_gap);
}

function summarizeRegeneration(
  previous: ChatMessage,
  next: Pick<ChatMessage, "text" | "confidence_score">,
): string {
  const parts: string[] = [];
  if (previous.confidence_score !== undefined && next.confidence_score !== undefined) {
    const delta = Math.round((next.confidence_score - previous.confidence_score) * 100);
    if (delta !== 0) parts.push(`Confidence ${delta > 0 ? "+" : ""}${delta} pts`);
  }
  if (previous.text.trim() !== next.text.trim()) parts.push("Updated answer text");
  if (parts.length === 0) return "Regenerated answer";
  return parts.join(" · ");
}

function hasCollapsibleDetails(message: ChatMessage) {
  if (message.role !== "agent" || message.isServiceError) return false;
  const sa = message.structured_answer;
  const hasStructured = Boolean(
    sa?.policy || sa?.steps || sa?.owner || sa?.evidence || sa?.next_action,
  );
  return !!(
    hasStructured ||
    message.confidence_reasons?.length ||
    message.regenerationSummary ||
    message.retrieval_debug ||
    message.next_step ||
    message.knowledge_gap
  );
}

function processingProgress(status: KnowledgeProcessingStatusApi): number {
  switch (status) {
    case "uploaded":
      return 10;
    case "extracting":
      return 25;
    case "extracted":
      return 40;
    case "chunking":
      return 55;
    case "chunked":
      return 70;
    case "embedding":
      return 85;
    case "ready":
    case "failed":
      return 100;
    default:
      return 0;
  }
}

function KnowledgePage() {
  const user = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();
  const { ref: librarySectionRef } = useLazyWhenVisible();
  const { ref: askPanelRef, isVisible: askPanelVisible } = useLazyWhenVisible();
  const [retrievalSettingsRequested, setRetrievalSettingsRequested] = useState(false);
  const [processingPollActive, setProcessingPollActive] = useState(false);

  const bootstrapQuery = useKnowledgeBootstrapQuery();
  const [librarySnapshot, setLibrarySnapshot] = useState<KnowledgeLibrarySnapshot | null>(() =>
    loadKnowledgeLibrarySnapshot(),
  );
  const libraryHealthQuery = useKnowledgeLibraryHealthQuery(
    true,
    processingPollActive,
    librarySnapshot?.libraryHealth,
  );
  const retrievalSettingsQuery = useKnowledgeRetrievalSettingsQuery(
    Boolean(user?.id) && askPanelVisible && retrievalSettingsRequested,
  );
  const uploadMutation = useUploadKnowledgeDocumentMutation();
  const updateDocumentMutation = useUpdateKnowledgeDocumentMutation();
  const deleteDocumentMutation = useDeleteKnowledgeDocumentMutation();
  const reindexDocumentMutation = useReindexKnowledgeDocumentMutation();
  const createFolderMutation = useCreateKnowledgeFolderMutation();
  const resolveGapMutation = useResolveKnowledgeGapMutation();
  const updateRetrievalSettingsMutation = useUpdateKnowledgeRetrievalSettingsMutation();

  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);
  const [createFolderName, setCreateFolderName] = useState("");
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [createFolderError, setCreateFolderError] = useState("");
  const [docId, setDocId] = useState<string | null>(null);
  const [activeChunkId, setActiveChunkId] = useState<string | null>(null);
  const [documentTab, setDocumentTab] = useState<DocumentDetailTab>("preview");
  const [openedDocumentTabs, setOpenedDocumentTabs] = useState<Set<DocumentDetailTab>>(new Set());
  const [askInput, setAskInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [animatingMessageId, setAnimatingMessageId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeSources, setActiveSources] = useState<KnowledgeCitationApi[]>([]);
  const [lastConfidence, setLastConfidence] = useState<number | null>(null);
  const [retrievalSettings, setRetrievalSettings] = useState<KnowledgeRetrievalSettingsApi | null>(
    null,
  );
  const [showRetrievalPanel, setShowRetrievalPanel] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [isDocumentOpen, setIsDocumentOpen] = useState(false);
  const [versions, setVersions] = useState<KnowledgeDocumentVersionApi[]>([]);
  const [versionCompare, setVersionCompare] = useState<KnowledgeVersionCompareApi | null>(null);
  const [compareLeftId, setCompareLeftId] = useState<string>("");
  const [compareRightId, setCompareRightId] = useState<string>("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [uploadError, setUploadError] = useState("");
  const [uploadWarning, setUploadWarning] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [activeFolder, setActiveFolder] = useState<string | "All">("All");
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | "All">("All");
  const [workflowFilter, setWorkflowFilter] = useState<WorkflowState | "All">("All");
  const [sortMode, setSortMode] = useState<SortMode>("recent");
  const [healthFilter, setHealthFilter] = useState<HealthFilter>("all");
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [pendingDocumentIds, setPendingDocumentIds] = useState<Set<string>>(new Set());
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const followChatScrollRef = useRef(true);
  const chatHydratedUserIdRef = useRef<string | null>(null);
  const [form, setForm] = useState({
    title: "",
    folderId: "",
    sourceType: "SOP" as SourceType,
    version: "v1.0",
    visibility: "Internal-only" as Visibility,
    status: "Draft" as DocumentStatus,
    owner: "",
    effectiveDate: new Date().toISOString().slice(0, 10),
  });

  const documentsQuery = useKnowledgeDocumentsQuery(
    true,
    processingPollActive,
    librarySnapshot?.documents,
  );
  const debouncedSearchTerm = useDebouncedValue(searchTerm, LIBRARY_DEBOUNCE_MS);
  const debouncedActiveFolder = useDebouncedValue(activeFolder, LIBRARY_DEBOUNCE_MS);
  const debouncedStatusFilter = useDebouncedValue(statusFilter, LIBRARY_DEBOUNCE_MS);
  const debouncedWorkflowFilter = useDebouncedValue(workflowFilter, LIBRARY_DEBOUNCE_MS);
  const debouncedSortMode = useDebouncedValue(sortMode, LIBRARY_DEBOUNCE_MS);
  const debouncedHealthFilter = useDebouncedValue(healthFilter, LIBRARY_DEBOUNCE_MS);

  const libraryFolders = useMemo<LibraryFolder[]>(
    () => {
      if (!bootstrapQuery.data) return librarySnapshot?.folders ?? [];
      return bootstrapQuery.data.folders.map((row) => ({
        id: row.id,
        kind: row.folder_kind,
        name: row.name,
      }));
    },
    [bootstrapQuery.data, librarySnapshot?.folders],
  );
  const bootstrapDocuments = useMemo(
    () =>
      bootstrapQuery.data
        ? bootstrapQuery.data.recent_documents.map(documentSummaryFromApi)
        : [],
    [bootstrapQuery.data],
  );
  const documents =
    documentsQuery.data ??
    librarySnapshot?.documents ??
    bootstrapDocuments;
  const knowledgePermissions = bootstrapQuery.data?.permissions ?? null;
  const libraryHealth: KnowledgeLibraryHealthApi = useMemo(() => {
    if (libraryHealthQuery.data) return libraryHealthQuery.data;
    if (bootstrapQuery.data) {
      return {
        ...EMPTY_LIBRARY_HEALTH,
        ...bootstrapQuery.data.library_health,
        open_gaps: [],
      };
    }
    return librarySnapshot?.libraryHealth ?? EMPTY_LIBRARY_HEALTH;
  }, [bootstrapQuery.data, libraryHealthQuery.data, librarySnapshot?.libraryHealth]);
  const hasLibraryContent = documents.length > 0 || libraryFolders.length > 0;
  const loadingDocs = bootstrapQuery.isLoading && !bootstrapQuery.data && !librarySnapshot && !hasLibraryContent;
  const showingLibrarySnapshot = Boolean(librarySnapshot && documents === librarySnapshot.documents);
  const docsLoadError = bootstrapQuery.isError
    ? bootstrapQuery.error instanceof Error
      ? bootstrapQuery.error.message
      : "Could not load knowledge documents."
    : "";

  const selectedDoc = documents.find((item) => item.id === docId) ?? null;
  const selectedDocId = selectedDoc?.id ?? null;
  const approvedIndexedDocs = documents.filter(isRetrievalReady);
  const canAsk = (libraryHealth.ready_count ?? 0) > 0 || approvedIndexedDocs.length > 0;
  const suggestedQuestions = useMemo(
    () => buildSuggestedQuestions(documents, libraryFolders),
    [documents, libraryFolders],
  );
  const retrievalScopeLabel = useMemo(
    () => formatRetrievalScopeLabel(retrievalScope),
    [retrievalScope],
  );
  const canAdjustScope =
    knowledgePermissions?.can_adjust_retrieval_scope ??
    (user?.role === "bsg_leadership" || user?.role === "super_admin");

  const handleDocumentLoaded = useCallback(
    (document: KnowledgeDocument) => {
      patchKnowledgeDocumentsCache(queryClient, (current) =>
        current.map((item) => (item.id === document.id ? document : item)),
      );
    },
    [queryClient],
  );

  const { loadingDetail, loadingVersions } = useDocumentTabLoader({
    documentId: selectedDoc?.id ?? null,
    isOpen: isDocumentOpen,
    enabled: openedDocumentTabs.has(documentTab),
    activeTab: documentTab,
    onDocumentLoaded: handleDocumentLoaded,
    onVersionsLoaded: setVersions,
  });

  useEffect(() => {
    if (!isDocumentOpen) {
      setOpenedDocumentTabs(new Set());
      setVersions([]);
      setVersionCompare(null);
      setCompareLeftId("");
      setCompareRightId("");
      return;
    }
    setOpenedDocumentTabs((current) => new Set(current).add(documentTab));
  }, [documentTab, isDocumentOpen, selectedDoc?.id]);

  useEffect(() => {
    setVersions([]);
  }, [selectedDoc?.id]);

  const handleDocumentTabChange = (tab: string) => {
    setDocumentTab(tab as DocumentDetailTab);
    setOpenedDocumentTabs((current) => new Set(current).add(tab as DocumentDetailTab));
  };

  const draftCount = documents.filter((item) => item.status === "Draft").length;
  const indexingCount = documents.filter((item) => item.indexing).length;
  const archivedCount = documents.filter((item) => item.status === "Archived").length;
  const expiredCount = documents.filter((item) => item.workflowState === "Expired").length;
  const needsReindexCount = documents.filter((item) => item.workflowState === "Needs re-index").length;
  const healthFilters = [
    { id: "all" as const, label: "All", count: documents.length },
    { id: "ready" as const, label: "Ready", count: libraryHealth.ready_count || approvedIndexedDocs.length },
    { id: "needs_approval" as const, label: "Needs approval", count: libraryHealth.draft_count || draftCount },
    { id: "expired" as const, label: "Expired", count: libraryHealth.expired_count || expiredCount },
    { id: "needs_reindex" as const, label: "Needs re-index", count: libraryHealth.needs_reindex_count || needsReindexCount },
    { id: "indexing" as const, label: "Indexing", count: libraryHealth.indexing_count || indexingCount },
    { id: "archived" as const, label: "Archived", count: libraryHealth.archived_count || archivedCount },
  ];
  const libraryTodos = libraryHealth.open_gaps;
  const hasLibraryTodos =
    libraryTodos.length > 0 ||
    (libraryHealth.expired_count || expiredCount) > 0 ||
    (libraryHealth.needs_reindex_count || needsReindexCount) > 0 ||
    (!canAsk && documents.length > 0);
  const librarySnapshotSignature = useMemo(
    () => getKnowledgeLibrarySnapshotSignature(documents, libraryFolders, libraryHealth),
    [documents, libraryFolders, libraryHealth],
  );
  const cachedLibrarySnapshotSignature = useMemo(
    () =>
      librarySnapshot
        ? getKnowledgeLibrarySnapshotSignature(
            librarySnapshot.documents,
            librarySnapshot.folders,
            librarySnapshot.libraryHealth,
          )
        : "",
    [librarySnapshot],
  );

  useEffect(() => {
    const hasResolvedData = Boolean(bootstrapQuery.data || documentsQuery.data || libraryHealthQuery.data);
    if (!hasResolvedData || (documents.length === 0 && libraryFolders.length === 0)) return;
    if (librarySnapshotSignature === cachedLibrarySnapshotSignature) return;
    const snapshot = {
      documents,
      folders: libraryFolders,
      libraryHealth,
      savedAt: Date.now(),
    };
    setLibrarySnapshot(snapshot);
    saveKnowledgeLibrarySnapshot(snapshot);
  }, [
    bootstrapQuery.data,
    cachedLibrarySnapshotSignature,
    documents,
    documentsQuery.data,
    libraryFolders,
    libraryHealth,
    librarySnapshotSignature,
    libraryHealthQuery.data,
  ]);

  useEffect(() => {
    if (indexingCount > 0 && !processingPollActive) {
      setProcessingPollActive(true);
    }
    if (processingPollActive && indexingCount === 0 && !documentsQuery.isFetching && !libraryHealthQuery.isFetching) {
      setProcessingPollActive(false);
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeBootstrap });
    }
  }, [
    documentsQuery.isFetching,
    indexingCount,
    libraryHealthQuery.isFetching,
    processingPollActive,
    queryClient,
  ]);

  const activeFilterCount = [
    activeFolder !== "All",
    statusFilter !== "All",
    workflowFilter !== "All",
    sortMode !== "recent",
    healthFilter !== "all",
  ].filter(Boolean).length;
  const isLibraryControlSettling =
    searchTerm !== debouncedSearchTerm ||
    activeFolder !== debouncedActiveFolder ||
    statusFilter !== debouncedStatusFilter ||
    workflowFilter !== debouncedWorkflowFilter ||
    sortMode !== debouncedSortMode ||
    healthFilter !== debouncedHealthFilter;

  const clearLibraryFilters = () => {
    setActiveFolder("All");
    setStatusFilter("All");
    setWorkflowFilter("All");
    setSortMode("recent");
    setHealthFilter("all");
    setSearchTerm("");
  };

  const filteredDocuments = useMemo(() => {
    const query = debouncedSearchTerm.trim().toLowerCase();
    const filtered = documents.filter((item) => {
      const matchesFolder = debouncedActiveFolder === "All" || item.folderId === debouncedActiveFolder;
      const matchesStatus = debouncedStatusFilter === "All" || item.status === debouncedStatusFilter;
      const matchesWorkflow = debouncedWorkflowFilter === "All" || item.workflowState === debouncedWorkflowFilter;
      const matchesHealth =
        debouncedHealthFilter === "all" ||
        (debouncedHealthFilter === "ready" && isRetrievalReady(item)) ||
        (debouncedHealthFilter === "needs_approval" && item.status === "Draft") ||
        (debouncedHealthFilter === "expired" && item.workflowState === "Expired") ||
        (debouncedHealthFilter === "needs_reindex" && item.workflowState === "Needs re-index") ||
        (debouncedHealthFilter === "indexing" && item.indexing) ||
        (debouncedHealthFilter === "archived" && item.status === "Archived");
      const matchesSearch =
        !query ||
        [item.title, item.sourceType, item.owner, item.fileName, item.version]
          .join(" ")
          .toLowerCase()
          .includes(query);
      return matchesFolder && matchesStatus && matchesWorkflow && matchesHealth && matchesSearch;
    });

    const statusRank: Record<DocumentStatus, number> = { Approved: 0, Draft: 1, Archived: 2 };
    return [...filtered].sort((left, right) => {
      if (debouncedSortMode === "title") return left.title.localeCompare(right.title);
      if (debouncedSortMode === "approved") {
        const rankDelta = statusRank[left.status] - statusRank[right.status];
        return rankDelta || left.title.localeCompare(right.title);
      }
      if (debouncedSortMode === "indexed") {
        const indexedDelta = Number(right.indexed) - Number(left.indexed);
        return indexedDelta || left.title.localeCompare(right.title);
      }
      const leftTime = Date.parse(left.effectiveDate || "") || 0;
      const rightTime = Date.parse(right.effectiveDate || "") || 0;
      return rightTime - leftTime || left.title.localeCompare(right.title);
    });
  }, [
    debouncedActiveFolder,
    debouncedHealthFilter,
    debouncedSearchTerm,
    debouncedSortMode,
    debouncedStatusFilter,
    debouncedWorkflowFilter,
    documents,
  ]);

  const groupedDocuments = useMemo(
    () =>
      libraryFolders
        .filter((folder) => debouncedActiveFolder === "All" || folder.id === debouncedActiveFolder)
        .map((folder) => ({
          id: folder.id,
          kind: folder.kind,
          folderName: folder.name,
          items: filteredDocuments.filter((item) => item.folderId === folder.id),
          total: documents.filter((item) => item.folderId === folder.id).length,
        })),
    [debouncedActiveFolder, documents, filteredDocuments, libraryFolders],
  );

  const loadLibraryFolders = async (options?: { silent?: boolean }) => {
    if (!options?.silent) setLoadingFolders(true);
    try {
      const rows = await listKnowledgeFolders();
      setLibraryFolders(
        rows.map((row) => ({
          id: row.id,
          kind: row.folder_kind,
          name: row.name,
        })),
      );
    } catch {
      setLibraryFolders([]);
    } finally {
      if (!options?.silent) setLoadingFolders(false);
    }
  };

  useEffect(() => {
    const load = async () => {
      setLoadingDocs(true);
      setDocsLoadError("");
      try {
        const [rows] = await Promise.all([listKnowledgeDocuments(), loadLibraryFolders()]);
        const mapped = rows.map(documentFromApi);
        setDocuments(mapped);
        setDocId((current) =>
          current && mapped.some((item) => item.id === current) ? current : (mapped[0]?.id ?? null),
        );
      } catch (err) {
        setDocuments([]);
        setDocId(null);
        setDocsLoadError(
          err instanceof Error ? err.message : "Could not load knowledge documents.",
        );
      } finally {
        setLoadingDocs(false);
      }
    };
    void load();
  }, []);

  useEffect(() => {
    if (libraryFolders.length === 0) return;
    setForm((current) =>
      current.folderId ? current : { ...current, folderId: libraryFolders[0].id },
    );
    setCollapsedFolders((current) =>
      current.size > 0 ? current : new Set(libraryFolders.map((folder) => folder.id)),
    );
  }, [libraryFolders]);

  useEffect(() => {
    if (!selectedDocId || !isDocumentOpen) return;
    let cancelled = false;
    setLoadingDocDetail(true);
    void getKnowledgeDocument(selectedDocId)
      .then((row) => {
        if (cancelled) return;
        const mapped = documentFromApi(row);
        setDocuments((current) => current.map((item) => (item.id === mapped.id ? mapped : item)));
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingDocDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isDocumentOpen, selectedDocId]);

  useEffect(() => {
    if (!selectedDocId || !isDocumentOpen) return;
    void listKnowledgeDocumentVersions(selectedDocId)
      .then(setVersions)
      .catch(() => setVersions([]));
    setVersionCompare(null);
    setCompareLeftId("");
    setCompareRightId("");
  }, [isDocumentOpen, selectedDocId]);

  const scrollChatToEnd = (force = false) => {
    if (!force && !followChatScrollRef.current) return;
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  const isNearChatBottom = () => {
    const container = chatScrollRef.current;
    if (!container) return true;
    return container.scrollHeight - container.scrollTop - container.clientHeight <= CHAT_SCROLL_THRESHOLD_PX;
  };

  const handleChatScroll = () => {
    const following = isNearChatBottom();
    followChatScrollRef.current = following;
    setShowJumpToBottom(!following);
  };

  const jumpToChatBottom = () => {
    followChatScrollRef.current = true;
    setShowJumpToBottom(false);
    scrollChatToEnd(true);
  };

  const announceAgentMessage = (text: string) => {
    setLiveAnnouncement(`Knowledge Agent: ${text}`);
  };

  const finishAgentAnswer = (
    messageId: string,
    text: string,
    options?: { skipAnimation?: boolean; isHistorical?: boolean },
  ) => {
    const displayText = text.trim();
    if (!displayText) {
      announceAgentMessage(NO_KNOWLEDGE_ANSWER);
      return;
    }
    if (options?.skipAnimation || options?.isHistorical || !shouldAnimateAnswer(displayText)) {
      announceAgentMessage(displayText);
      return;
    }
    setAnimatingMessageId(messageId);
  };

  useEffect(() => {
    if (!liveAnnouncement) return;
    const timer = window.setTimeout(() => setLiveAnnouncement(""), 1500);
    return () => window.clearTimeout(timer);
  }, [liveAnnouncement]);

  useEffect(() => {
    scrollChatToEnd();
  }, [asking, messages.length, animatingMessageId]);

  useEffect(() => {
    const userId = user?.id;
    if (!userId) {
      chatHydratedUserIdRef.current = null;
      return;
    }
    if (chatHydratedUserIdRef.current === userId) return;
    chatHydratedUserIdRef.current = userId;
    const stored = loadKnowledgeChatSession(userId);
    setMessages(stored?.messages ?? []);
    setActiveConversationId(stored?.conversationId ?? null);
    setAnimatingMessageId(null);
  }, [user?.id]);

  useEffect(() => {
    const userId = user?.id;
    if (!userId || chatHydratedUserIdRef.current !== userId) return;
    if (messages.length === 0) {
      clearKnowledgeChatSession(userId);
      return;
    }
    saveKnowledgeChatSession(userId, { messages, conversationId: activeConversationId });
  }, [user?.id, messages, activeConversationId]);

  useEffect(() => {
    if (!isDocumentOpen || !activeChunkId || documentTab !== "chunks") return;
    window.setTimeout(() => {
      document
        .getElementById(`chunk-${activeChunkId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 120);
  }, [activeChunkId, documentTab, isDocumentOpen]);

  const setField = <Key extends keyof typeof form>(key: Key, value: (typeof form)[Key]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const validateFile = (file: File | null) => {
    if (!file) return "Choose a PDF, DOCX, TXT, MD, or CSV file.";
    const lower = file.name.toLowerCase();
    if (!acceptedExtensions.some((extension) => lower.endsWith(extension))) {
      return "Unsupported file type. Use PDF, DOCX, TXT, MD, or CSV.";
    }
    return "";
  };

  const handleFile = (file: File | null) => {
    const error = validateFile(file);
    setUploadError(error);
    setSelectedFile(error ? null : file);
    if (file && !form.title) {
      setField("title", file.name.replace(/\.[^/.]+$/, ""));
    }
  };

  const resetUpload = () => {
    setUploadState("idle");
    setUploadProgress(0);
    setUploadError("");
    setUploadWarning("");
    setSelectedFile(null);
    setForm({
      title: "",
      folderId: libraryFolders[0]?.id ?? "",
      sourceType: "SOP",
      version: "v1.0",
      visibility: "Internal-only",
      status: "Draft",
      owner: "",
      effectiveDate: new Date().toISOString().slice(0, 10),
    });
  };

  const handleUpload = async () => {
    const error = validateFile(selectedFile);
    if (error || !form.title.trim() || !form.owner.trim() || !form.folderId) {
      setUploadState("error");
      setUploadError(error || "Document title, folder, and owner/approver are required.");
      return;
    }
    if (form.status === "Approved" && !form.effectiveDate) {
      setUploadState("error");
      setUploadError("Approved uploads require an effective date before indexing.");
      return;
    }

    const file = selectedFile;
    if (!file) return;

    setUploadState("uploading");
    setUploadError("");
    setUploadWarning("");
    setUploadProgress(38);
    try {
      const fields = uploadFormToApi(form);
      const apiFields = Object.fromEntries(
        Object.entries(fields).map(([key, value]) => [key, value ?? ""]),
      ) as Record<string, string>;
      const row = await uploadMutation.mutateAsync({ file, fields: apiFields });
      const newDocument = documentFromApi(row);
      setProcessingPollActive(true);
      patchKnowledgeDocumentsCache(queryClient, (current) => {
        const exists = current.some((item) => item.id === newDocument.id);
        return exists
          ? current.map((item) => (item.id === newDocument.id ? newDocument : item))
          : [...current, newDocument];
      });
      setActiveFolder("All");
      setStatusFilter("All");
      setSearchTerm("");
      setDocId(newDocument.id);
      setCollapsedFolders((current) => {
        const next = new Set(current);
        next.delete(newDocument.folderId);
        return next;
      });
      setUploadProgress(100);
      setUploadState("success");
      if (newDocument.qualityWarnings.length > 0) {
        setUploadWarning(newDocument.qualityWarnings.join(" "));
      }
      window.setTimeout(() => {
        setIsUploadOpen(false);
        resetUpload();
      }, 900);
    } catch (err) {
      setUploadState("error");
      setUploadError(err instanceof Error ? err.message : "Upload failed.");
    }
  };

  const updateDocument = async (id: string, patch: Partial<KnowledgeDocument>) => {
    const current = documents.find((item) => item.id === id);
    if (!current) return;
    const optimistic = { ...current, ...patch };
    setPendingDocumentIds((ids) => new Set(ids).add(id));
    patchKnowledgeDocumentsCache(queryClient, (rows) =>
      rows.map((item) => (item.id === id ? optimistic : item)),
    );
    try {
      const apiPatch = documentToApiPatch(patch);
      const cleaned = Object.fromEntries(
        Object.entries(apiPatch).filter(([, value]) => value !== undefined),
      ) as Record<string, string>;
      await updateDocumentMutation.mutateAsync({ id, patch: cleaned });
    } catch {
      patchKnowledgeDocumentsCache(queryClient, (rows) =>
        rows.map((item) => (item.id === id ? current : item)),
      );
    } finally {
      setPendingDocumentIds((ids) => {
        const next = new Set(ids);
        next.delete(id);
        return next;
      });
    }
  };

  const renameDocument = async (document: KnowledgeDocument) => {
    const title = window.prompt("Rename document", document.title)?.trim();
    if (title) await updateDocument(document.id, { title });
  };

  const deleteDocument = async (document: KnowledgeDocument) => {
    const previous = documents;
    setDocuments((current) => current.filter((item) => item.id !== document.id));
    setDocId((current) =>
      current === document.id
        ? (previous.find((item) => item.id !== document.id)?.id ?? null)
        : current,
    );
    setIsDocumentOpen(false);
    try {
      await deleteDocumentMutation.mutateAsync(document.id);
    } catch {
      queryClient.setQueryData(queryKeys.knowledgeDocuments, previous);
      setDocId(previousDocId);
    } finally {
      setPendingDocumentIds((ids) => {
        const next = new Set(ids);
        next.delete(document.id);
        return next;
      });
    }
  };

  const reindexDocument = async (document: KnowledgeDocument) => {
    setProcessingPollActive(true);
    setPendingDocumentIds((ids) => new Set(ids).add(document.id));
    patchKnowledgeDocumentsCache(queryClient, (rows) =>
      rows.map((item) =>
        item.id === document.id
          ? {
              ...item,
              indexed: false,
              indexing: true,
              processingStatus: "embedding",
              processingLabel: "Generating Embeddings...",
            }
          : item,
      ),
    );
    try {
      await reindexDocumentMutation.mutateAsync(document.id);
    } catch {
      patchKnowledgeDocumentsCache(queryClient, (rows) =>
        rows.map((item) =>
          item.id === document.id
            ? {
                ...item,
                indexed: document.indexed,
                indexing: false,
                processingStatus: document.processingStatus,
                processingLabel: document.processingLabel,
              }
            : item,
        ),
      );
    } finally {
      setPendingDocumentIds((ids) => {
        const next = new Set(ids);
        next.delete(document.id);
        return next;
      });
    }
  };

  const downloadDocument = async (document: KnowledgeDocument) => {
    try {
      const { blob, fileName } = await downloadKnowledgeDocumentFile(document.id);
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = fileName ?? document.fileName;
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Download failed.");
    }
  };

  const submitAsk = async (questionOverride?: string, options?: { skipUserMessage?: boolean }) => {
    const question = (questionOverride ?? askInput).trim();
    if (!question || asking || !canAsk) return;
    followChatScrollRef.current = true;
    setShowJumpToBottom(false);
    if (!options?.skipUserMessage) {
      setMessages((current) => [...current, createUserMessage(question)]);
      if (!questionOverride) setAskInput("");
    }
    setAsking(true);
    const conversationHistory = buildConversationHistory(messages);
    const agentMsgId = createChatMessageId();

    // Create a stub agent message immediately so the user sees a response forming
    const stub: ChatMessage = {
      id: agentMsgId,
      role: "agent",
      text: "",
      isStreaming: true,
    };
    setMessages((current) => [...current, stub]);

    let gotDone = false;
    let streamAnswer = "";
    let streamFlushRaf: number | null = null;
    const flushStreamToUi = () => {
      streamFlushRaf = null;
      const liveText = streamAnswer;
      setMessages((current) =>
        current.map((msg) =>
          msg.id === agentMsgId ? { ...msg, text: liveText, wasStreamed: true } : msg,
        ),
      );
      scrollChatToEnd();
    };
    const scheduleStreamFlush = () => {
      if (streamFlushRaf !== null) return;
      streamFlushRaf = window.requestAnimationFrame(flushStreamToUi);
    };
    const askOptions = {
      conversationHistory,
      answerMode: inferAnswerMode(question),
      conversationId: activeConversationId,
    };

    try {
      const response = await askKnowledgeAgent(question, {
        includeHistories: retrievalSettings?.include_histories ?? true,
        maxSources: retrievalSettings?.max_sources ?? 5,
        minRelevanceScore: retrievalSettings?.min_confidence ?? 0.25,
        project: retrievalSettings?.project ?? undefined,
        department: retrievalSettings?.department ?? undefined,
      });
      const agentMsg: ChatMessage = {
        role: "agent",
        text: response.answer_text,
        next_step: response.next_step,
        confidence_score: response.confidence_score,
        confidence_reasons: response.confidence_reasons,
        structured_answer: response.structured_answer,
        knowledge_gap: response.knowledge_gap,
        citations: response.citations,
      };
      setMessages((current) => {
        const next = [...current, agentMsg];
        setAnimatingMessageIndex(next.length - 1);
        return next;
      });
      setActiveSources(response.citations);
      setLastConfidence(response.confidence_score);
      if (response.citations[0]) {
        openDocumentWithChunk(
          response.citations[0].document_id,
          response.citations[0].chunk_id,
          false,
        );
      }
    } catch {
      setMessages((current) =>
        current.map((msg) =>
          msg.id === agentMsgId
            ? { ...msg, text: msg.text || "Couldn't reach the agent — retry?", isStreaming: false, isServiceError: !msg.text, retryQuestion: !msg.text ? question : undefined }
            : msg,
        ),
      );
    } finally {
      if (streamFlushRaf !== null) {
        window.cancelAnimationFrame(streamFlushRaf);
      }
      setMessages((current) =>
        current.map((msg) =>
          msg.id === agentMsgId && msg.isStreaming ? { ...msg, isStreaming: false } : msg,
        ),
      );
      setAsking(false);
      void invalidateKnowledgeAgentQueries(queryClient);
    }
  };

  const regenerateAgentAnswer = async (agentMessageId: string) => {
    if (asking || !canAsk) return;
    const agentIndex = messages.findIndex((message) => message.id === agentMessageId);
    if (agentIndex < 0) return;
    const previousAgentMessage = messages[agentIndex];
    const question = findPrecedingUserQuestion(messages, agentMessageId);
    if (!question) return;

    const priorMessages = messages.slice(0, agentIndex);
    const conversationHistory = buildConversationHistory(priorMessages.slice(0, -1));
    const agentMsgId = createChatMessageId();

    followChatScrollRef.current = true;
    setShowJumpToBottom(false);
    setMessages((current) => {
      const next = current.filter((message) => message.id !== agentMessageId);
      next.splice(agentIndex, 0, { id: agentMsgId, role: "agent", text: "", isStreaming: true });
      return next;
    });
    setAnimatingMessageId(null);
    setAsking(true);

    let gotDone = false;
    let streamAnswer = "";
    const askOptions = {
      conversationHistory,
      answerMode: inferAnswerMode(question),
      conversationId: activeConversationId,
    };

    try {
      for await (const event of streamKnowledgeAsk(question, askOptions)) {
        if (event.type === "status") {
          setMessages((current) =>
            current.map((msg) =>
              msg.id === agentMsgId ? { ...msg, streamPhase: event.phase } : msg,
            ),
          );
        } else if (event.type === "delta") {
          streamAnswer += event.text;
          const liveText = streamAnswer;
          setMessages((current) =>
            current.map((msg) =>
              msg.id === agentMsgId ? { ...msg, text: liveText, wasStreamed: true } : msg,
            ),
          );
          scrollChatToEnd();
        } else if (event.type === "done") {
          gotDone = true;
          const resolvedText = resolveAgentAnswerText(
            { text: streamAnswer, structured_answer: event.structured_answer, next_step: event.next_step },
            event.answer_text,
          );
          const agentMsg: ChatMessage = {
            id: agentMsgId,
            role: "agent",
            text: resolvedText,
            isStreaming: false,
            wasStreamed: true,
            query_id: event.query_id,
            confidence_score: event.confidence_score,
            confidence_reasons: event.confidence_reasons,
            next_step: event.next_step || undefined,
            structured_answer: event.structured_answer ?? null,
            retrieval_debug: event.retrieval_debug ?? null,
            regenerationSummary: summarizeRegeneration(previousAgentMessage, {
              text: resolvedText,
              confidence_score: event.confidence_score,
            }),
            detailsExpanded: (event.confidence_score ?? 1) < LOW_CONFIDENCE_THRESHOLD,
          };
          setMessages((current) =>
            current.map((msg) => (msg.id === agentMsgId ? agentMsg : msg)),
          );
          if (event.conversation_id) {
            setActiveConversationId(event.conversation_id);
          }
          finishAgentAnswer(agentMsgId, resolvedText, { skipAnimation: true });
        } else if (event.type === "error") {
          setMessages((current) =>
            current.map((msg) =>
              msg.id === agentMsgId
                ? { ...msg, text: "Couldn't reach the agent — retry?", isStreaming: false, isServiceError: true, retryQuestion: question }
                : msg,
            ),
          );
        }
      }
      if (!gotDone && !streamAnswer.trim()) {
        setMessages((current) =>
          current.map((msg) =>
            msg.id === agentMsgId
              ? { ...msg, text: "Couldn't reach the agent — retry?", isStreaming: false, isServiceError: true, retryQuestion: question }
              : msg,
          ),
        );
      }
    } catch {
      setMessages((current) =>
        current.map((msg) =>
          msg.id === agentMsgId
            ? { ...msg, text: "Couldn't reach the agent — retry?", isStreaming: false, isServiceError: true, retryQuestion: question }
            : msg,
        ),
      );
    } finally {
      setAsking(false);
      void invalidateKnowledgeAgentQueries(queryClient);
    }
  };

  const setMessageFeedback = async (messageId: string, feedback: "up" | "down", comment?: string) => {
    let queryId: string | null = null;
    let previousFeedback: "up" | "down" | undefined;
    let nextFeedback: "up" | "down" | undefined;

    setMessages((current) => {
      const target = current.find((msg) => msg.id === messageId);
      if (!target || target.role !== "agent") return current;

      queryId = target.query_id ?? null;
      previousFeedback = target.feedback;
      const togglingOff = target.feedback === feedback && comment === undefined;
      nextFeedback = togglingOff ? undefined : feedback;

      return current.map((msg) => {
        if (msg.id !== messageId) return msg;
        return {
          ...msg,
          feedback: nextFeedback,
          feedbackComment: comment !== undefined ? comment : msg.feedbackComment,
        };
      });
    });

    if (!nextFeedback || !queryId) return;

    try {
      await submitKnowledgeFeedback({
        query_id: queryId,
        rating: feedback,
        comment: comment ?? null,
      });
    } catch {
      setMessages((current) =>
        current.map((msg) => (msg.id === messageId ? { ...msg, feedback: previousFeedback } : msg)),
      );
    }
  };

  const setFeedbackComment = (messageId: string, comment: string) => {
    setMessages((current) =>
      current.map((msg) => (msg.id === messageId ? { ...msg, feedbackComment: comment } : msg)),
    );
  };

  const retryAsk = async (question: string, errorMessageId: string) => {
    if (!question || asking || !canAsk) return;
    setMessages((current) => current.filter((message) => message.id !== errorMessageId));
    await submitAsk(question, { skipUserMessage: true });
  };

  const openConversation = async (conversation: KnowledgeConversationSummaryApi) => {
    if (asking) return;
    try {
      const loaded = await getKnowledgeConversation(conversation.id);
      setAnimatingMessageId(null);
      setActiveConversationId(loaded.id);
      setMessages(messagesFromConversation(loaded.turns));
      followChatScrollRef.current = true;
      setShowJumpToBottom(false);
      scrollChatToEnd(true);
    } catch {
      window.alert("Could not load that conversation.");
    }
  };

  const saveRetrievalScope = async () => {
    if (!scopeDraft || savingScope) return;
    setSavingScope(true);
    try {
      const saved = await updateRetrievalSettingsMutation.mutateAsync({
        ...scopeDraft,
        project: scopeDraft.project?.trim() || null,
        department: scopeDraft.department?.trim() || null,
      });
      setRetrievalScope(saved);
      setScopeDraft(saved);
    } catch {
      window.alert("Could not update retrieval scope.");
    } finally {
      setSavingScope(false);
    }
  };

  const toggleMessageDetails = (messageId: string) => {
    setMessages((current) =>
      current.map((msg) =>
        msg.id === messageId && msg.role === "agent"
          ? { ...msg, detailsExpanded: !isMessageDetailsOpen(msg) }
          : msg,
      ),
    );
  };

  const copyAgentAnswer = async (messageId: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(messageId);
      window.setTimeout(() => {
        setCopiedMessageId((current) => (current === messageId ? null : current));
      }, 2000);
    } catch {
      window.alert("Could not copy to clipboard.");
    }
  };

  const handleAsk = (event: FormEvent) => {
    event.preventDefault();
    void submitAsk();
  };

  const clearConversation = () => {
    setMessages([]);
    setActiveConversationId(null);
    setAnimatingMessageId(null);
    setCopiedMessageId(null);
    setAskInput("");
    followChatScrollRef.current = true;
    setShowJumpToBottom(false);
    if (user?.id) clearKnowledgeChatSession(user.id);
  };

  const toggleFolder = (folderId: string) => {
    setCollapsedFolders((current) => {
      const next = new Set(current);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  };

  const toggleFolderLimit = (folderId: string) => {
    setExpandedFolders((current) => {
      const next = new Set(current);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  };

  const openDocument = (id: string) => {
    openDocumentWithChunk(id, null, true);
  };

  const openDocumentWithChunk = (id: string, chunkId: string | null, openDialog = true) => {
    const tab: DocumentDetailTab = chunkId ? "chunks" : "preview";
    setDocId(id);
    setActiveChunkId(chunkId);
    setDocumentTab(tab);
    setOpenedDocumentTabs((current) => new Set(current).add(tab));
    if (openDialog) setIsDocumentOpen(true);
  };

  const prefillUploadFromGap = (gap: KnowledgeGapApi | KnowledgeGapTodoApi) => {
    const sourceMap: Record<string, SourceType> = {
      sop: "SOP",
      guide: "Guide",
      training_document: "Training Document",
      project_charter: "Project Charter",
      escalation_note: "Escalation Note",
      lesson_learned: "Lesson Learned",
    };
    const suggestedFolder =
      libraryFolders.find((folder) => folder.kind === gap.suggested_folder_kind) ??
      libraryFolders[0];
    setForm((current) => ({
      ...current,
      title: gap.suggested_title ?? current.title,
      folderId: suggestedFolder?.id ?? current.folderId,
      sourceType: sourceMap[gap.suggested_source_type ?? "sop"] ?? "SOP",
      status: "Draft",
    }));
    setIsUploadOpen(true);
  };

  const handleResolveGap = async (gapId: string) => {
    const previousHealth = queryClient.getQueryData<KnowledgeLibraryHealthApi>(queryKeys.knowledgeLibraryHealth);
    queryClient.setQueryData<KnowledgeLibraryHealthApi>(queryKeys.knowledgeLibraryHealth, (current) => {
      if (!current) return current;
      return {
        ...current,
        open_gaps: current.open_gaps.filter((gap) => gap.id !== gapId),
      };
    });
    try {
      await resolveGapMutation.mutateAsync(gapId);
    } catch {
      if (previousHealth) queryClient.setQueryData(queryKeys.knowledgeLibraryHealth, previousHealth);
    }
  };

  const openCreateFolder = () => {
    setCreateFolderName("");
    setCreateFolderError("");
    setIsCreateFolderOpen(true);
  };

  const submitCreateFolder = async (event: FormEvent) => {
    event.preventDefault();
    const name = createFolderName.trim();
    if (!name || creatingFolder) return;
    setCreatingFolder(true);
    setCreateFolderError("");
    try {
      const created = await createFolderMutation.mutateAsync({ name });
      setCollapsedFolders((current) => {
        const next = new Set(current);
        next.delete(created.id);
        return next;
      });
      setActiveFolder(created.id);
      setCreateFolderName("");
      setIsCreateFolderOpen(false);
    } catch (err) {
      setCreateFolderError(err instanceof Error ? err.message : "Could not create folder.");
    } finally {
      setCreatingFolder(false);
    }
  };

  const runVersionCompare = async () => {
    if (!selectedDoc || !compareLeftId || !compareRightId || compareLeftId === compareRightId)
      return;
    try {
      const result = await compareKnowledgeDocumentVersions(
        selectedDoc.id,
        compareLeftId,
        compareRightId,
      );
      setVersionCompare(result);
    } catch {
      setVersionCompare(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 px-1 py-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            <Library className="h-3.5 w-3.5" />
            Operational Knowledge Agent
          </div>
          <h1 className="mt-2 text-xl font-semibold tracking-tight text-foreground">
            Knowledge workspace
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SummaryPill
            icon={<ShieldCheck className="h-3.5 w-3.5" />}
            label="Retrievable"
            value={approvedIndexedDocs.length}
          />
          <SummaryPill
            icon={<Loader2 className="h-3.5 w-3.5" />}
            label="Indexing"
            value={indexingCount}
          />
          <SummaryPill
            icon={<Archive className="h-3.5 w-3.5" />}
            label="Drafts"
            value={draftCount}
          />
          <Button
            className="h-9 gap-2 bg-[color:var(--brand)] text-xs text-[color:var(--brand-foreground)]"
            onClick={() => setIsUploadOpen(true)}
          >
            <Upload className="h-4 w-4" />
            Upload Document
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-12 items-stretch gap-5 xl:h-[calc(100vh-11.5rem)] xl:min-h-[44rem]">
        <div className="col-span-12 flex min-h-0 flex-col gap-5 xl:col-span-4">
          <Card className="shrink-0 border-transparent bg-card/80">
            <div className="border-b border-border/70 px-4 py-3">
              <div className="flex items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-[color:var(--brand)]" />
                <span className="text-sm font-semibold tracking-tight text-foreground">
                  Sources
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {activeSources.length > 0
                  ? `${activeSources.length} source${activeSources.length !== 1 ? "s" : ""} used`
                  : "Ask a question to see sources"}
              </p>
            </div>

            {activeSources.length === 0 ? (
              <div className="flex items-center gap-3 px-4 py-5 text-xs text-muted-foreground">
                <FileText className="h-7 w-7 shrink-0 opacity-25" />
                <span>Source documents will appear here after you ask a question.</span>
              </div>
            ) : (
              <div className="max-h-56 space-y-2 overflow-y-auto px-3 py-3">
                {activeSources.map((src, idx) => {
                  const pct = Math.round(src.relevance_score * 100);
                  return (
                    <button
                      key={`${src.document_id}-${idx}`}
                      type="button"
                      onClick={() => openDocumentWithChunk(src.document_id, src.chunk_id, true)}
                      className="w-full rounded-md border border-border/70 bg-secondary/40 p-3 text-left transition-colors hover:bg-secondary/80"
                    >
                      <div className="mb-1 flex items-start justify-between gap-2">
                        <span className="line-clamp-2 text-[11px] font-semibold leading-tight text-foreground">
                          {src.title}
                        </span>
                        {pct > 0 && (
                          <span className="shrink-0 rounded-sm bg-[color:var(--brand)]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[color:var(--brand)]">
                            {pct}%
                          </span>
                        )}
                      </div>
                      <div className="mb-2 text-[10px] text-muted-foreground">
                        {src.source_type
                          .replace(/_/g, " ")
                          .replace(/\b\w/g, (c) => c.toUpperCase())}
                        {src.folder_name ? ` | ${src.folder_name}` : ""}
                        {src.page_number ? ` | p. ${src.page_number}` : ""}
                      </div>
                      {pct > 0 && (
                        <div className="h-1 w-full overflow-hidden rounded-full bg-border/60">
                          <div
                            className="h-full rounded-full bg-[color:var(--brand)]"
                            style={{ width: `${Math.min(pct, 100)}%` }}
                          />
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </Card>

          <Card className="flex min-h-0 flex-1 flex-col border-transparent bg-card/80">
            <SectionHeader
              title="Knowledge Library"
              sub={libraryLoading ? "Loading library..." : `${documents.length} governed documents`}
              right={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1 px-2.5 text-[10px] shadow-none"
                  onClick={openCreateFolder}
                >
                  <Plus className="h-3 w-3" />
                  Create
                </Button>
              }
            />

            {docsLoadError && (
              <div className="rounded-md border border-[color:var(--danger)]/30 bg-[color:var(--danger)]/8 px-3 py-2 text-xs text-[color:var(--danger)]">
                {docsLoadError}
              </div>
            )}

            <div className="space-y-3">
              <div className="flex flex-wrap gap-1.5">
                {healthFilters.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setHealthFilter(item.id)}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-[10px] font-medium transition",
                      healthFilter === item.id
                        ? "border-[color:var(--brand)]/40 bg-[color:var(--brand)]/10 text-[color:var(--brand)]"
                        : "border-border/70 bg-transparent text-muted-foreground hover:bg-secondary/70 hover:text-foreground",
                    )}
                  >
                    {item.label} {item.count}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <div className="relative min-w-0 flex-1">
                  <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Search title, owner, type, or version"
                    className="h-9 pl-9 text-xs shadow-none"
                  />
                </div>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 shrink-0 gap-1.5 px-3 text-xs shadow-none"
                    >
                      <Filter className="h-3.5 w-3.5" />
                      Filters
                      {activeFilterCount > 0 && (
                        <span className="rounded-full bg-[color:var(--brand)]/15 px-1.5 text-[10px] font-semibold text-[color:var(--brand)]">
                          {activeFilterCount}
                        </span>
                      )}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="w-72 space-y-3 p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-foreground">Library filters</span>
                      {activeFilterCount > 0 && (
                        <button
                          type="button"
                          onClick={clearLibraryFilters}
                          className="text-[10px] text-muted-foreground hover:text-foreground"
                        >
                          Clear
                        </button>
                      )}
                    </div>
                    <Field label="Folder">
                      <Select
                        value={activeFolder}
                        onValueChange={(value) => setActiveFolder(value)}
                      >
                        <SelectTrigger className="h-8 text-xs shadow-none">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="All">All folders</SelectItem>
                          {libraryFolders.map((folder) => (
                            <SelectItem key={folder.id} value={folder.id}>
                              {folder.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="Status">
                      <Select
                        value={statusFilter}
                        onValueChange={(value) => setStatusFilter(value as DocumentStatus | "All")}
                      >
                        <SelectTrigger className="h-8 text-xs shadow-none">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="All">All statuses</SelectItem>
                          {statuses.map((status) => (
                            <SelectItem key={status} value={status}>
                              {status}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="Workflow">
                      <Select
                        value={workflowFilter}
                        onValueChange={(value) => setWorkflowFilter(value as WorkflowState | "All")}
                      >
                        <SelectTrigger className="h-8 text-xs shadow-none">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="All">All workflow states</SelectItem>
                          {workflowStates.map((state) => (
                            <SelectItem key={state} value={state}>
                              {state}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="Sort by">
                      <Select
                        value={sortMode}
                        onValueChange={(value) => setSortMode(value as SortMode)}
                      >
                        <SelectTrigger className="h-8 text-xs shadow-none">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="recent">Recently effective</SelectItem>
                          <SelectItem value="title">Title A-Z</SelectItem>
                          <SelectItem value="approved">Approved first</SelectItem>
                          <SelectItem value="indexed">Ready first</SelectItem>
                        </SelectContent>
                      </Select>
                    </Field>
                  </PopoverContent>
                </Popover>
              </div>
            </div>

            <div className="mt-4 min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
              {libraryLoading ? (
                <div className="space-y-4" aria-busy="true" aria-label="Loading knowledge library">
                  {[0, 1, 2].map((section) => (
                    <div key={section} className="space-y-2">
                      <Skeleton className="h-4 w-28" />
                      {[0, 1].map((row) => (
                        <div key={row} className="rounded-md bg-secondary/40 p-3">
                          <div className="flex items-start gap-3">
                            <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
                            <div className="min-w-0 flex-1 space-y-2">
                              <Skeleton className="h-4 w-3/4" />
                              <Skeleton className="h-3 w-1/2" />
                              <div className="flex gap-1.5">
                                <Skeleton className="h-5 w-16 rounded-full" />
                                <Skeleton className="h-5 w-14 rounded-full" />
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              ) : (
                <>
                  {groupedDocuments.map((group) => {
                    const isCollapsed = collapsedFolders.has(group.id);
                    const isExpanded = expandedFolders.has(group.id);
                    const visibleItems = isExpanded
                      ? group.items
                      : group.items.slice(0, folderPreviewLimit);
                    const hiddenCount = Math.max(group.items.length - visibleItems.length, 0);

                    return (
                      <section key={group.id}>
                        <button
                          type="button"
                          onClick={() => toggleFolder(group.id)}
                          className="mb-2 flex w-full items-center justify-between rounded-md px-1 py-1 text-left hover:bg-secondary/60"
                          aria-expanded={!isCollapsed}
                        >
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                            {isCollapsed ? (
                              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                            ) : (
                              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                            )}
                            {folderIcon(group.kind, group.folderName)}
                            {group.folderName}
                          </div>
                          <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">
                            {group.items.length} of {group.total}
                          </span>
                        </button>
                        <div className={cn("space-y-2", isCollapsed && "hidden")}>
                          {group.items.length === 0 && (
                            <div className="rounded-md border border-dashed border-border/70 bg-secondary/30 px-3 py-3 text-xs text-muted-foreground">
                              No documents in this folder yet.
                            </div>
                          )}
                          {visibleItems.map((item) => (
                            <button
                              key={item.id}
                              onClick={() => openDocument(item.id)}
                              className={cn(
                                "w-full rounded-md p-3 text-left transition",
                                docId === item.id
                                  ? "bg-[color:var(--brand)]/7"
                                  : "bg-transparent hover:bg-secondary/70",
                              )}
                            >
                              <div className="flex items-start gap-3">
                                <div className="mt-0.5 rounded-md bg-secondary p-1.5">
                                  <FileText className="h-4 w-4 text-muted-foreground" />
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-start justify-between gap-2">
                                    <div className="min-w-0">
                                      <p className="truncate text-sm font-medium text-foreground">
                                        {item.title}
                                      </p>
                                      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                                        {item.sourceType} | {item.version} | {item.owner}
                                      </p>
                                    </div>
                                    <span className="shrink-0 rounded bg-secondary px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
                                      {item.fileType}
                                    </span>
                                  </div>
                                  <div className="mt-2 flex flex-wrap items-center gap-1">
                                    <DocBadge label={item.workflowState} />
                                    <DocBadge label={item.status} />
                                    {item.qualityScore && (
                                      <QualityScoreBadge score={item.qualityScore} />
                                    )}
                                    {item.semanticRelevance != null &&
                                      item.semanticRelevance > 0 && (
                                        <span className="rounded bg-[color:var(--brand)]/10 px-1.5 py-0.5 text-[9px] font-medium text-[color:var(--brand)]">
                                          {Math.round(item.semanticRelevance * 100)}% match
                                        </span>
                                      )}
                                    {item.indexing && (
                                      <DocBadge label={item.processingLabel} tone="info" />
                                    )}
                                    {item.processingStatus === "ready" && (
                                      <DocBadge label="Ready" tone="success" />
                                    )}
                                    {item.processingStatus === "failed" && (
                                      <DocBadge label="Failed" tone="danger" />
                                    )}
                                  </div>
                                </div>
                              </div>
                            </button>
                          ))}
                          {group.items.length > folderPreviewLimit && (
                            <button
                              type="button"
                              onClick={() => toggleFolderLimit(group.id)}
                              className="w-full rounded-md border border-dashed border-border/70 px-3 py-2 text-center text-xs font-medium text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                            >
                              {isExpanded
                                ? "Show less"
                                : `Show all ${group.items.length} documents${hiddenCount ? ` (${hiddenCount} more)` : ""}`}
                            </button>
                          )}
                        </div>
                      </section>
                    );
                  })}
                  {filteredDocuments.length === 0 &&
                    libraryFolders.length === 0 &&
                    !docsLoadError && (
                      <div className="rounded-md border border-dashed border-border/70 bg-secondary/30 p-6 text-center text-xs text-muted-foreground">
                        No folders yet. Use{" "}
                        <span className="font-medium text-foreground">Create</span> to add your
                        first folder.
                      </div>
                    )}
                  {filteredDocuments.length === 0 && libraryFolders.length > 0 && (
                    <div className="rounded-md bg-secondary/50 p-6 text-center text-xs text-muted-foreground">
                      {documents.length === 0 && !docsLoadError ? (
                        <span>
                          No documents are visible for{" "}
                          {user?.organisation?.name ?? "your organisation"}.
                          {user?.role === "client"
                            ? " Client accounts cannot access the knowledge library API."
                            : " Try the PM dev account (pm@bsg.dev) or upload a new document."}
                        </span>
                      ) : (
                        "No documents match the current filters."
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </Card>
        </div>

        <div ref={askPanelRef} className="col-span-12 min-h-0 xl:col-span-8">
          <Card className="flex h-full min-h-0 flex-col border-transparent bg-card/80 p-0">
            <div className="border-b border-border/70 px-5 py-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
                      <Bot className="h-4 w-4" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold tracking-tight text-foreground">
                        Ask Knowledge Agent
                      </h3>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        Answers use approved, ready documents only.
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-[color:var(--success)]/10 px-2.5 py-1 text-[10px] font-medium text-[color:var(--success)]">
                    {approvedIndexedDocs.length} sources ready
                  </span>
                  <AiBadge
                    confidence={lastConfidence != null ? Math.round(lastConfidence * 100) : 0}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
                    onClick={() => setShowRetrievalPanel((v) => !v)}
                  >
                    <Settings2 className="h-3.5 w-3.5" />
                    Retrieval
                  </Button>
                </div>
              </div>
            </div>

            {showRetrievalPanel && (
              <div className="px-5 pt-3">
                <KnowledgeRetrievalPanel
                  canManage={canManageRetrieval}
                  onChange={setRetrievalSettings}
                />
              </div>
            )}

            <div className="px-5 pt-3">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Suggested questions
              </div>
              <div className="flex flex-wrap gap-2">
                {suggestedQuestions.map((question) => (
                  <button
                    key={question}
                    type="button"
                    onClick={() => setAskInput(question)}
                    className="rounded-full border border-border/70 bg-card px-3 py-1.5 text-[11px] text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                  >
                    {question}
                  </button>
                ))}
              </div>
            </div>

            <div className="mx-5 mt-4 min-h-0 flex-1 space-y-4 overflow-y-auto rounded-md bg-secondary/35 p-4 text-xs">
              {messages.map((message, index) => {
                const isAnimating = message.role === "agent" && index === animatingMessageIndex;
                const showAgentDetails = message.role === "agent" && !isAnimating;

                return (
                  <div
                    key={`${message.role}-${index}`}
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
                      )}
                    >
                      <div
                        className={cn(
                          "mb-1 flex items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wider",
                          message.role === "user" ? "text-white/70" : "text-muted-foreground",
                        )}
                      >
                        <span>{message.role === "user" ? "You" : "Knowledge Agent"}</span>
                        {showAgentDetails &&
                          message.confidence_score !== undefined &&
                          message.confidence_score > 0 && (
                            <span className="rounded-sm bg-[color:var(--success)]/15 px-1.5 py-0.5 text-[color:var(--success)] normal-case">
                              {Math.round(message.confidence_score * 100)}% confidence
                            </span>
                          )}
                      </div>
                      {isAnimating ? (
                        <TypewriterText
                          text={message.text}
                          className="leading-5"
                          onProgress={scrollChatToEnd}
                          onComplete={() => setAnimatingMessageIndex(null)}
                        />
                      ) : (
                        <p className="leading-5">{message.text}</p>
                      )}
                      {showAgentDetails &&
                        message.confidence_reasons &&
                        message.confidence_reasons.length > 0 && (
                          <div className="mt-2.5 rounded-sm border border-border/60 bg-secondary/40 px-2.5 py-2">
                            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                              Why this confidence
                            </div>
                            <ul className="space-y-0.5 text-[11px] leading-4 text-muted-foreground">
                              {message.confidence_reasons.map((reason) => (
                                <li key={reason}>• {reason}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      {showAgentDetails && message.structured_answer && (
                        <div className="mt-2.5 space-y-2 rounded-sm border border-border/60 bg-secondary/30 p-2.5">
                          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                            Operational answer
                          </div>
                          {message.structured_answer.policy && (
                            <StructuredField
                              label="Policy"
                              value={message.structured_answer.policy}
                            />
                          )}
                          {message.structured_answer.steps && (
                            <StructuredField
                              label="Steps"
                              value={message.structured_answer.steps}
                            />
                          )}
                          {message.structured_answer.owner && (
                            <StructuredField
                              label="Owner"
                              value={message.structured_answer.owner}
                            />
                          )}
                          {message.structured_answer.evidence && (
                            <StructuredField
                              label="Evidence"
                              value={message.structured_answer.evidence}
                            />
                          )}
                          {message.structured_answer.next_action && (
                            <StructuredField
                              label="Next action"
                              value={message.structured_answer.next_action}
                            />
                          )}
                        </div>
                      )}
                      {showAgentDetails && message.knowledge_gap && (
                        <div className="mt-2.5 rounded-sm border border-[color:var(--warning)]/30 bg-[color:var(--warning)]/8 p-2.5">
                          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--warning)]">
                            Missing knowledge
                          </div>
                          <p className="text-[11px] leading-4 text-foreground">
                            {message.knowledge_gap.message}
                          </p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-7 text-[10px]"
                              onClick={() => prefillUploadFromGap(message.knowledge_gap!)}
                            >
                              Upload related document
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              className="h-7 text-[10px]"
                              onClick={() => setWorkflowFilter("Needs review")}
                            >
                              Review pending documents
                            </Button>
                          </div>
                        </div>
                      )}
                      {showAgentDetails && message.next_step && (
                        <div className="mt-2.5 rounded-sm border border-[color:var(--brand)]/20 bg-[color:var(--brand)]/5 px-2.5 py-2">
                          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--brand)]/70">
                            Recommended next step
                          </div>
                          <p className="text-[11px] leading-4 text-foreground">
                            {message.next_step}
                          </p>
                        </div>
                      )}
                      {showAgentDetails && message.citations && message.citations.length > 0 && (
                        <div className="mt-2.5 border-t border-border/50 pt-2">
                          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                            Sources
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {message.citations.map((item) => (
                              <button
                                key={`${item.document_id}-${item.citation_label}`}
                                type="button"
                                onClick={() =>
                                  openDocumentWithChunk(item.document_id, item.chunk_id, true)
                                }
                                className="rounded-md border border-border/70 bg-secondary/50 px-2 py-1 text-[10px] text-foreground hover:bg-secondary"
                              >
                                {item.title}
                                {item.relevance_score > 0 && (
                                  <span className="ml-1 text-muted-foreground">
                                    · {Math.round(item.relevance_score * 100)}%
                                  </span>
                                )}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })
              )}
              {asking && !messages.some((message) => message.isStreaming) && (
                <div className="flex gap-3">
                  <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground">
                    <Bot className="h-3.5 w-3.5" />
                  </div>
                  <div className="rounded-md bg-card px-3 py-3 text-xs text-muted-foreground">
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Knowledge Agent
                    </div>
                    <TypingIndicator />
                  </div>
                </div>
              )}
              <div ref={chatEndRef} aria-hidden="true" />
              </div>
              {showJumpToBottom && (
                <button
                  type="button"
                  onClick={jumpToChatBottom}
                  className="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-full border border-border/70 bg-card px-3 py-1.5 text-[10px] font-medium text-foreground shadow-sm transition-colors hover:bg-secondary"
                >
                  Jump to latest
                </button>
              )}
            </div>

            <form className="flex shrink-0 flex-col gap-2 p-5 pt-4" onSubmit={handleAsk}>
              {!loadingDocs && !canAsk && (
                <p className="text-xs text-muted-foreground">Upload and approve documents first.</p>
              )}
              <div className="flex items-center gap-2">
              <Textarea
                placeholder={loadingDocs ? "" : canAsk ? "Ask about an SOP, guide, or historical issue..." : "Upload and approve documents first"}
                value={askInput}
                disabled={loadingDocs || asking || !canAsk}
                onChange={(event) => setAskInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submitAsk();
                  }
                }}
                rows={1}
                className="min-h-10 flex-1 resize-none rounded-md border-border bg-card py-2.5 text-sm shadow-none focus-visible:border-[color:var(--brand)] focus-visible:ring-0"
              />
              <Button
                type="submit"
                disabled={loadingDocs || asking || !canAsk}
                className="h-10 shrink-0 gap-2 bg-[color:var(--brand)] px-4 text-xs text-[color:var(--brand-foreground)]"
              >
                <Send className="h-3.5 w-3.5" />
                {asking ? "Asking" : "Ask"}
              </Button>
              </div>
            </form>
          </Card>
        </div>

        <div className="hidden">
          <Card className="border-transparent bg-card/80">
            <div className="border-b border-border/70 px-4 py-3">
              <div className="flex items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-[color:var(--brand)]" />
                <span className="text-sm font-semibold tracking-tight text-foreground">
                  Sources
                </span>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {activeSources.length > 0
                  ? `${activeSources.length} source${activeSources.length !== 1 ? "s" : ""} used`
                  : "Ask a question to see sources"}
              </p>
            </div>

            {activeSources.length === 0 ? (
              <div className="flex flex-col items-center gap-3 px-4 py-8 text-center text-xs text-muted-foreground">
                <FileText className="h-8 w-8 opacity-25" />
                <span>Source documents will appear here after you ask a question.</span>
              </div>
            ) : (
              <div className="space-y-2 px-3 py-3">
                {activeSources.map((src, idx) => {
                  const pct = Math.round(src.relevance_score * 100);
                  return (
                    <button
                      key={`${src.document_id}-${idx}`}
                      type="button"
                      onClick={() => openDocumentWithChunk(src.document_id, src.chunk_id, true)}
                      className="w-full rounded-md border border-border/70 bg-secondary/40 p-3 text-left hover:bg-secondary/80 transition-colors"
                    >
                      <div className="mb-1 flex items-start justify-between gap-2">
                        <span className="line-clamp-2 text-[11px] font-semibold text-foreground leading-tight">
                          {src.title}
                        </span>
                        {pct > 0 && (
                          <span className="shrink-0 rounded-sm bg-[color:var(--brand)]/10 px-1.5 py-0.5 text-[10px] font-semibold text-[color:var(--brand)]">
                            {pct}%
                          </span>
                        )}
                      </div>
                      <div className="mb-2 text-[10px] text-muted-foreground">
                        {src.source_type
                          .replace(/_/g, " ")
                          .replace(/\b\w/g, (c) => c.toUpperCase())}
                        {src.folder_name ? ` · ${src.folder_name}` : ""}
                        {src.page_number ? ` · p. ${src.page_number}` : ""}
                      </div>
                      {src.chunk_preview && (
                        <p className="mb-2 line-clamp-3 text-[10px] leading-4 text-muted-foreground">
                          {src.chunk_preview}
                        </p>
                      )}
                      {pct > 0 && (
                        <div className="h-1 w-full overflow-hidden rounded-full bg-border/60">
                          <div
                            className="h-full rounded-full bg-[color:var(--brand)]"
                            style={{ width: `${Math.min(pct, 100)}%` }}
                          />
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      </div>

      <Dialog open={isDocumentOpen && !!selectedDoc} onOpenChange={setIsDocumentOpen}>
        <DialogContent className="flex h-[86vh] w-[min(92vw,68rem)] max-w-none flex-col overflow-hidden">
          {selectedDoc && (
            <>
              <DialogHeader className="shrink-0">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <DialogTitle>{selectedDoc.title}</DialogTitle>
                    <DialogDescription>
                      {selectedDoc.folder} | {selectedDoc.fileName}
                    </DialogDescription>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {selectedDoc.workflowState !== selectedDoc.status && <DocBadge label={selectedDoc.workflowState} />}
                    <DocBadge label={selectedDoc.status} />
                  </div>
                </div>
              </DialogHeader>

              <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[1fr_18rem]">
                <div className="min-h-0 rounded-md bg-secondary/50 p-4">
                  <Tabs
                    value={documentTab}
                    onValueChange={setDocumentTab}
                    className="flex h-full min-h-0 flex-col"
                  >
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <TabsList className="h-8 bg-card/70">
                        <TabsTrigger
                          value="preview"
                          className="px-2.5 py-1 text-xs data-[state=active]:shadow-none"
                        >
                          Preview
                        </TabsTrigger>
                        <TabsTrigger
                          value="metadata"
                          className="px-2.5 py-1 text-xs data-[state=active]:shadow-none"
                        >
                          Metadata
                        </TabsTrigger>
                        <TabsTrigger
                          value="chunks"
                          className="px-2.5 py-1 text-xs data-[state=active]:shadow-none"
                        >
                          Chunks
                        </TabsTrigger>
                        <TabsTrigger
                          value="versions"
                          className="px-2.5 py-1 text-xs data-[state=active]:shadow-none"
                        >
                          Versions
                        </TabsTrigger>
                        <TabsTrigger
                          value="evidence"
                          className="px-2.5 py-1 text-xs data-[state=active]:shadow-none"
                        >
                          Evidence
                        </TabsTrigger>
                      </TabsList>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {selectedDoc.indexing && (
                          <DocBadge label={selectedDoc.processingLabel} tone="info" />
                        )}
                        {selectedDoc.processingStatus === "ready" && (
                          <DocBadge label="Ready" tone="success" />
                        )}
                        {selectedDoc.processingStatus === "failed" && (
                          <DocBadge label="Failed" tone="danger" />
                        )}
                      </div>
                    </div>
                    {selectedDoc.indexing && (
                      <Progress value={processingProgress(selectedDoc.processingStatus)} className="h-1.5" />
                    )}

                    <TabsContent
                      value="preview"
                      className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2"
                    >
                      <div className="space-y-3 text-sm leading-6">
                        {selectedDoc.preview.map((paragraph) => (
                          <FormattedPreview key={paragraph} text={paragraph} />
                        ))}
                      </div>
                      {!isRetrievalReady(selectedDoc) && (
                        <div className="mt-4 rounded-md bg-[color:var(--warning)]/10 p-3 text-xs leading-5 text-muted-foreground">
                          This document is not currently eligible for Ask Knowledge Agent retrieval.
                          It must be Approved and Ready.
                        </div>
                      )}
                    </TabsContent>

                    <TabsContent
                      value="metadata"
                      className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2"
                    >
                      <div className="grid gap-2 text-xs sm:grid-cols-2">
                        <InfoTile label="Source type" value={selectedDoc.sourceType} />
                        <InfoTile label="Visibility" value={selectedDoc.visibility} />
                        <InfoTile label="Workflow" value={selectedDoc.workflowState} />
                        <InfoTile label="Status" value={selectedDoc.status} />
                        <InfoTile label="Version" value={selectedDoc.version} />
                        <InfoTile label="Owner/Approver" value={selectedDoc.owner} />
                        <InfoTile
                          label="Effective date"
                          value={selectedDoc.effectiveDate || "Not set"}
                        />
                        <InfoTile
                          label="Approved by"
                          value={selectedDoc.approvedByName || "Not approved"}
                        />
                        <InfoTile label="Chunks" value={String(selectedDoc.chunkCount)} />
                        <InfoTile label="Citations" value={String(selectedDoc.citationCount)} />
                      </div>
                      {selectedDoc.qualityScore && (
                        <div className="mt-4 rounded-md border border-border/70 bg-card/60 p-3">
                          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                            Document quality
                          </div>
                          <QualityScoreBadge score={selectedDoc.qualityScore} detailed />
                        </div>
                      )}
                    </TabsContent>

                    <TabsContent
                      value="chunks"
                      className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2"
                    >
                      {loadingDocDetail && selectedDoc.chunks.length === 0 ? (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          Loading chunks...
                        </div>
                      ) : (
                        <div className="space-y-2 text-xs">
                          {selectedDoc.chunks.length === 0 &&
                            selectedDoc.preview.map((paragraph, index) => (
                              <div
                                key={`${selectedDoc.id}-chunk-${index}`}
                                className="rounded-md border border-border/70 bg-card/60 p-3"
                              >
                                <div className="mb-1 font-medium text-muted-foreground">
                                  Chunk {index + 1}
                                </div>
                                <FormattedPreview text={paragraph} compact />
                              </div>
                            ))}
                          {selectedDoc.chunks.map((chunk) => (
                            <div
                              key={chunk.id}
                              id={`chunk-${chunk.id}`}
                              className={cn(
                                "rounded-md border bg-card/60 p-3",
                                activeChunkId === chunk.id
                                  ? "border-[color:var(--brand)] ring-2 ring-[color:var(--brand)]/20"
                                  : "border-border/70",
                              )}
                            >
                              <div className="mb-1 flex items-center justify-between gap-2 font-medium text-muted-foreground">
                                <span>
                                  Chunk {chunk.chunkIndex + 1}
                                  {chunk.sectionTitle ? ` · ${chunk.sectionTitle}` : ""}
                                  {chunk.pageNumber ? ` · p. ${chunk.pageNumber}` : ""}
                                </span>
                                {activeChunkId === chunk.id && (
                                  <span className="rounded bg-[color:var(--brand)]/10 px-1.5 py-0.5 text-[10px] text-[color:var(--brand)]">
                                    Cited
                                  </span>
                                )}
                              </div>
                              <FormattedPreview text={chunk.chunkText} compact />
                            </div>
                          ))}
                        </div>
                      )}
                    </TabsContent>

                    <TabsContent
                      value="versions"
                      className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2"
                    >
                      <div className="space-y-3 text-xs">
                        {versions.map((version) => (
                          <div
                            key={version.id}
                            className="rounded-md border border-border/70 bg-card/60 p-3"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="font-semibold text-foreground">{version.version}</div>
                              {version.is_active && <DocBadge label="Active" tone="success" />}
                            </div>
                            <div className="mt-1 text-muted-foreground">
                              Uploaded {new Date(version.uploaded_at).toLocaleString()}
                              {version.uploaded_by_name ? ` by ${version.uploaded_by_name}` : ""}
                            </div>
                            <div className="mt-1 text-muted-foreground">
                              {version.chunk_count} chunks
                              {version.approved_by_name
                                ? ` · Approved by ${version.approved_by_name}`
                                : ""}
                            </div>
                          </div>
                        ))}
                        {versions.length >= 2 && (
                          <div className="rounded-md border border-dashed border-border/70 bg-card/40 p-3">
                            <div className="mb-2 flex items-center gap-2 font-semibold text-foreground">
                              <GitCompare className="h-3.5 w-3.5" />
                              Compare versions
                            </div>
                            <div className="grid gap-2 sm:grid-cols-2">
                              <Select value={compareLeftId} onValueChange={setCompareLeftId}>
                                <SelectTrigger className="h-8 text-xs">
                                  <SelectValue placeholder="Left version" />
                                </SelectTrigger>
                                <SelectContent>
                                  {versions.map((v) => (
                                    <SelectItem key={v.id} value={v.id}>
                                      {v.version}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <Select value={compareRightId} onValueChange={setCompareRightId}>
                                <SelectTrigger className="h-8 text-xs">
                                  <SelectValue placeholder="Right version" />
                                </SelectTrigger>
                                <SelectContent>
                                  {versions.map((v) => (
                                    <SelectItem key={v.id} value={v.id}>
                                      {v.version}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              className="mt-2 h-8 text-xs"
                              onClick={() => void runVersionCompare()}
                            >
                              Compare
                            </Button>
                            {versionCompare && (
                              <div className="mt-3 space-y-2 rounded-md bg-secondary/50 p-3">
                                <div className="font-medium text-foreground">
                                  {versionCompare.left_version} vs {versionCompare.right_version}
                                </div>
                                <p className="text-muted-foreground">{versionCompare.summary}</p>
                                {versionCompare.added_sections.length > 0 && (
                                  <div>
                                    <div className="font-medium text-foreground">What changed</div>
                                    <ul className="mt-1 list-disc pl-4 text-muted-foreground">
                                      {versionCompare.added_sections.map((line) => (
                                        <li key={line}>{line}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                {(versionCompare.left_approved_by ||
                                  versionCompare.right_approved_by) && (
                                  <div className="text-muted-foreground">
                                    Approved by:{" "}
                                    {versionCompare.right_approved_by ||
                                      versionCompare.left_approved_by ||
                                      "Unknown"}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </TabsContent>

                    <TabsContent
                      value="evidence"
                      className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2"
                    >
                      <div className="rounded-md border border-border/70 bg-card/60 p-4 text-xs leading-5 text-muted-foreground">
                        {isRetrievalReady(selectedDoc)
                          ? `This document has been cited ${selectedDoc.citationCount} time(s) and is eligible for Ask Knowledge Agent answers.`
                          : "This document is visible for review, but it will not be used as answer evidence until it is approved and ready."}
                      </div>
                    </TabsContent>
                  </Tabs>
                </div>

                <aside className="min-h-0 space-y-3 overflow-y-auto pr-1">
                  <div className="rounded-md bg-secondary/50 p-3 text-xs">
                    <h4 className="font-semibold text-foreground">Document details</h4>
                    <dl className="mt-3 space-y-2 text-muted-foreground">
                      <MetaRow label="Version" value={selectedDoc.version} />
                      <MetaRow label="Owner" value={selectedDoc.owner} />
                      <MetaRow label="Effective" value={selectedDoc.effectiveDate || "Not set"} />
                      <MetaRow label="File" value={`${selectedDoc.fileType}`} />
                    </dl>
                  </div>
                  <div className="space-y-1.5 border-t border-border/60 pt-2">
                    <div className="grid grid-cols-2 gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 justify-start rounded-md border border-border/70 bg-card/60 px-2 text-xs text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                        onClick={() => void renameDocument(selectedDoc)}
                      >
                        Rename
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 justify-start gap-1.5 rounded-md border border-border/70 bg-card/60 px-2 text-xs text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                        onClick={() => void reindexDocument(selectedDoc)}
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                        Re-index
                      </Button>
                    </div>
                    <div className="grid grid-cols-[4.5rem_1fr] items-center gap-2 rounded-md border border-border/70 bg-card/60 px-2 py-1 text-xs">
                      <span className="text-muted-foreground">Folder</span>
                      <Select
                        value={selectedDoc.folderId}
                        onValueChange={(value) =>
                          void updateDocument(selectedDoc.id, { folderId: value })
                        }
                      >
                        <SelectTrigger className="h-8 border-transparent bg-transparent px-2 text-xs shadow-none hover:bg-secondary/70">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {libraryFolders.map((folder) => (
                            <SelectItem key={folder.id} value={folder.id}>
                              {folder.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid grid-cols-[4.5rem_1fr] items-center gap-2 rounded-md border border-border/70 bg-card/60 px-2 py-1 text-xs">
                      <span className="text-muted-foreground">Status</span>
                      <Select
                        value={selectedDoc.status}
                        onValueChange={(value) =>
                          void updateDocument(selectedDoc.id, { status: value as DocumentStatus })
                        }
                      >
                        <SelectTrigger className="h-8 border-transparent bg-transparent px-2 text-xs shadow-none hover:bg-secondary/70">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {statuses.map((status) => (
                            <SelectItem key={status} value={status}>
                              {status}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-full justify-start gap-1.5 rounded-md border border-border/70 bg-card/60 px-2 text-xs text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                      onClick={() => void downloadDocument(selectedDoc)}
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download uploaded file
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-full justify-start gap-1.5 rounded-md border border-[color:var(--danger)]/20 bg-[color:var(--danger)]/5 px-2 text-xs text-[color:var(--danger)] hover:bg-[color:var(--danger)]/10 hover:text-[color:var(--danger)]"
                      onClick={() => void deleteDocument(selectedDoc)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete document
                    </Button>
                  </div>
                </aside>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog
        open={isCreateFolderOpen}
        onOpenChange={(open) => {
          setIsCreateFolderOpen(open);
          if (!open) {
            setCreateFolderName("");
            setCreateFolderError("");
          }
        }}
      >
        <DialogContent className="max-w-sm gap-6 border border-border p-6 shadow-none sm:rounded-lg">
          <DialogHeader className="space-y-0">
            <DialogTitle className="text-base font-semibold">Create folder</DialogTitle>
          </DialogHeader>
          <form className="space-y-6" onSubmit={(event) => void submitCreateFolder(event)}>
            <Field label="Choose the folder name" className="space-y-2.5">
              <Input
                value={createFolderName}
                onChange={(event) => setCreateFolderName(event.target.value)}
                placeholder="e.g. SOPs, Guides, Histories"
                className="h-10 text-sm shadow-none"
                autoFocus
              />
            </Field>
            {createFolderError && (
              <p className="text-xs text-[color:var(--danger)]">{createFolderError}</p>
            )}
            <DialogFooter className="gap-2 pt-2 sm:justify-end sm:space-x-0">
              <Button
                type="button"
                variant="outline"
                className="shadow-none"
                onClick={() => setIsCreateFolderOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={creatingFolder || !createFolderName.trim()}
                className="bg-[color:var(--brand)] text-[color:var(--brand-foreground)] shadow-none"
              >
                {creatingFolder ? "Saving..." : "Confirm"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={isUploadOpen}
        onOpenChange={(open) => {
          setIsUploadOpen(open);
          if (!open) resetUpload();
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Upload Document</DialogTitle>
            <DialogDescription>
              Add a governed source. The agent can retrieve it only after it is approved and
              indexed.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr]">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                handleFile(event.dataTransfer.files[0] ?? null);
              }}
              className="flex min-h-64 flex-col items-center justify-center rounded-md border border-dashed border-border/70 bg-secondary/40 p-6 text-center text-xs transition hover:bg-secondary/70"
            >
              <Upload className="mb-3 h-7 w-7 text-muted-foreground" />
              <div className="font-medium text-foreground">
                {selectedFile ? selectedFile.name : "Drop file here"}
              </div>
              <div className="mt-1 text-muted-foreground">
                or click to choose PDF, DOCX, TXT, MD, or CSV
              </div>
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept={acceptedExtensions.join(",")}
              className="hidden"
              onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
            />

            <div className="grid grid-cols-2 gap-3">
              <Field className="col-span-2" label="Document title">
                <Input
                  value={form.title}
                  onChange={(event) => setField("title", event.target.value)}
                  className="h-9 text-xs shadow-none"
                />
              </Field>
              <Field label="Folder">
                <Select
                  value={form.folderId}
                  onValueChange={(value) => setField("folderId", value)}
                >
                  <SelectTrigger className="h-9 text-xs shadow-none">
                    <SelectValue placeholder="Select folder" />
                  </SelectTrigger>
                  <SelectContent>
                    {libraryFolders.map((folder) => (
                      <SelectItem key={folder.id} value={folder.id}>
                        {folder.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Source type">
                <Select
                  value={form.sourceType}
                  onValueChange={(value) => setField("sourceType", value as SourceType)}
                >
                  <SelectTrigger className="h-9 text-xs shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {sourceTypes.map((type) => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Version">
                <Input
                  value={form.version}
                  onChange={(event) => setField("version", event.target.value)}
                  className="h-9 text-xs shadow-none"
                />
              </Field>
              <Field label="Visibility">
                <Select
                  value={form.visibility}
                  onValueChange={(value) => setField("visibility", value as Visibility)}
                >
                  <SelectTrigger className="h-9 text-xs shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {visibilities.map((visibility) => (
                      <SelectItem key={visibility} value={visibility}>
                        {visibility}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Status">
                <Select
                  value={form.status}
                  onValueChange={(value) => setField("status", value as DocumentStatus)}
                >
                  <SelectTrigger className="h-9 text-xs shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {statuses.map((status) => (
                      <SelectItem key={status} value={status}>
                        {status}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Effective date">
                <Input
                  type="date"
                  value={form.effectiveDate}
                  onChange={(event) => setField("effectiveDate", event.target.value)}
                  className="h-9 text-xs shadow-none"
                />
              </Field>
              <Field className="col-span-2" label="Owner/Approver">
                <Input
                  value={form.owner}
                  onChange={(event) => setField("owner", event.target.value)}
                  className="h-9 text-xs shadow-none"
                />
              </Field>
            </div>
          </div>

          {uploadState !== "idle" && (
            <div className="rounded-md bg-secondary/50 p-3 text-xs">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-medium">
                  {uploadState === "uploading" && "Uploading document..."}
                  {uploadState === "success" && "Upload complete. Processing in background..."}
                  {uploadState === "error" && "Upload failed"}
                </span>
                {uploadState === "success" ? (
                  <CheckCircle2 className="h-4 w-4 text-[color:var(--success)]" />
                ) : null}
                {uploadState === "uploading" ? (
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                ) : null}
              </div>
              {uploadState !== "error" && <Progress value={uploadProgress} />}
              {uploadState === "error" && (
                <p className="text-[color:var(--danger)]">{uploadError}</p>
              )}
              {uploadState === "success" && (
                <p className="mt-2 text-muted-foreground">
                  The document is visible in the selected folder while chunks and embeddings are
                  prepared.
                </p>
              )}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setIsUploadOpen(false)}>
              Cancel
            </Button>
            <Button
              className="bg-[color:var(--brand)] text-[color:var(--brand-foreground)]"
              onClick={() => void handleUpload()}
              disabled={uploadState === "uploading"}
            >
              Upload
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StructuredField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <p className="mt-0.5 text-[11px] leading-4 text-foreground whitespace-pre-wrap">{value}</p>
    </div>
  );
}

function QualityScoreBadge({
  score,
  detailed = false,
}: {
  score: {
    score: number;
    max_score: number;
    criteria: Array<{ key: string; label: string; passed: boolean }>;
  };
  detailed?: boolean;
}) {
  const pct = Math.round((score.score / Math.max(score.max_score, 1)) * 100);
  return (
    <div className="inline-flex flex-col gap-1">
      <span className="inline-flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
        Quality {score.score}/{score.max_score} ({pct}%)
      </span>
      {detailed && (
        <div className="flex flex-wrap gap-1">
          {score.criteria.map((item) => (
            <span
              key={item.key}
              className={cn(
                "rounded px-1.5 py-0.5 text-[9px]",
                item.passed
                  ? "bg-[color:var(--success)]/10 text-[color:var(--success)]"
                  : "bg-secondary text-muted-foreground",
              )}
            >
              {item.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function SummaryPill({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="flex h-9 items-center gap-2 rounded-md bg-card px-3 text-xs">
      <span className="text-muted-foreground">{icon}</span>
      <span className="font-semibold text-foreground">{value}</span>
      <span className="text-muted-foreground">{label}</span>
    </div>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("space-y-1.5 text-xs", className)}>
      <span className="font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt>{label}</dt>
      <dd className="max-w-[10rem] text-right font-medium text-foreground">{value}</dd>
    </div>
  );
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/70 bg-card/60 p-3">
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-medium text-foreground">{value}</div>
    </div>
  );
}

function FormattedPreview({ text, compact = false }: { text: string; compact?: boolean }) {
  const lines = formatPreviewLines(text);
  return (
    <div className={cn("space-y-2", compact && "space-y-1.5")}>
      {lines.map((line, index) => {
        if (line.kind === "heading") {
          return (
            <h4
              key={`${line.text}-${index}`}
              className="pt-1 text-sm font-semibold text-foreground"
            >
              {line.text}
            </h4>
          );
        }
        if (line.kind === "bullet") {
          return (
            <div key={`${line.text}-${index}`} className="flex gap-2 pl-2 text-sm leading-6">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/60" />
              <span>{line.text}</span>
            </div>
          );
        }
        return (
          <p key={`${line.text}-${index}`} className="text-sm leading-6 text-foreground">
            {line.text}
          </p>
        );
      })}
    </div>
  );
}

function formatPreviewLines(
  text: string,
): Array<{ kind: "heading" | "bullet" | "paragraph"; text: string }> {
  const normalized = text
    .replace(
      /(Purpose|Scope|Procedure|Responsibilities|Requirements|Project Summary|Challenges Encountered|Actions Taken|Results|Recommendations|Best Practices|Lessons Learned|Quality Guidance)(?=[A-Z0-9-])/g,
      "\n$1\n",
    )
    .replace(/(Phase\s+\d+:\s*[^-]+)-\s*/g, "\n$1\n- ")
    .replace(/(?<![\d\n])([1-9]\d?\.\s+)/g, "\n$1")
    .replace(/(?<=[a-z0-9)%])-\s*(?=[A-Z][A-Za-z]+(?:\s|$))/g, "\n- ")
    .replace(/(?<=[.;:])\s+-\s*(?=[A-Z][A-Za-z]+(?:\s|$))/g, "\n- ");
  return normalized
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const clean = line.replace(/^-\s*/, "").trim();
      if (line.startsWith("-")) return { kind: "bullet", text: clean };
      if (/^\d+[.)]\s+/.test(line)) return { kind: "bullet", text: line };
      if (
        /^(Purpose|Scope|Procedure|Responsibilities|Requirements|Project Summary|Challenges Encountered|Actions Taken|Results|Recommendations|Best Practices|Lessons Learned|Quality Guidance)$/i.test(
          line,
        )
      ) {
        return { kind: "heading", text: line };
      }
      if (/^Phase\s+\d+:/i.test(line)) return { kind: "heading", text: line };
      if (/^[A-Z][A-Za-z0-9:() /-]{2,}$/.test(line) && line.length <= 90 && !/[.!?]$/.test(line)) {
        return { kind: "heading", text: line };
      }
      return { kind: "paragraph", text: line };
    });
}

function folderIcon(kind: KnowledgeFolderKind, name: string) {
  const className = "h-3.5 w-3.5 text-muted-foreground";
  if (kind === "sops" || name === "SOPs") return <Folder className={className} />;
  if (kind === "guides" || name === "Guides") return <Sparkles className={className} />;
  if (kind === "histories" || name === "Histories") return <History className={className} />;
  return <Folder className={className} />;
}

function DocBadge({ label, tone }: { label: string; tone?: "success" | "info" | "danger" }) {
  if (label === "Approved" || label === "Draft" || label === "Archived")
    return <StatusPill status={label} />;
  const classes =
    tone === "success"
      ? "border-[color:var(--success)]/30 bg-[color:var(--success)]/15 text-[color:var(--success)]"
      : tone === "danger"
        ? "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]"
        : "border-[color:var(--info)]/30 bg-[color:var(--info)]/15 text-[color:var(--info)]";
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-medium",
        classes,
      )}
    >
      {label}
    </span>
  );
}

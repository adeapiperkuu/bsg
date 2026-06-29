import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Card, SectionHeader, AiBadge, StatusPill } from "@/components/bsg/widgets";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  askKnowledgeAgent,
  compareKnowledgeDocumentVersions,
  createKnowledgeEvalQuestion,
  createKnowledgeFolder,
  deleteKnowledgeDocument,
  downloadKnowledgeDocumentFile,
  getKnowledgeBootstrap,
  getKnowledgeDocument,
  getKnowledgeEvalMetrics,
  getKnowledgeQueryAnswer,
  getKnowledgeRetrievalSettings,
  listAgentQueries,
  listKnowledgeEvalQuestions,
  listKnowledgeDocumentVersions,
  listKnowledgeFolders,
  reindexKnowledgeDocument,
  resolveKnowledgeGap,
  runKnowledgeEval,
  streamKnowledgeAsk,
  submitKnowledgeFeedback,
  updateKnowledgeRetrievalSettings,
  updateKnowledgeDocument,
  updateKnowledgeEvalQuestion,
  uploadKnowledgeDocument,
} from "@/lib/api";
import { TypewriterText } from "@/components/knowledge/TypewriterText";
import { TypingIndicator } from "@/components/knowledge/TypingIndicator";
import { KnowledgeLoadingScreen } from "@/components/knowledge/KnowledgeLoadingScreen";
import { useAuthStore } from "@/stores/useAuthStore";
import {
  documentFromApi,
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
  AgentQueryApi,
  KnowledgeCitationApi,
  KnowledgeDocumentVersionApi,
  KnowledgeEvalMetricsApi,
  KnowledgeEvalQuestionApi,
  KnowledgeEvalRunApi,
  KnowledgeFolderKind,
  KnowledgeGapApi,
  KnowledgeGapTodoApi,
  KnowledgeLibraryHealthApi,
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
  GitCompare,
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
  citations?: KnowledgeCitationApi[];
  retrieval_debug?: KnowledgeRetrievalDebugApi | null;
  regenerationSummary?: string;
  query_id?: string | null;
  feedback?: "up" | "down";
  feedbackComment?: string;
  isServiceError?: boolean;
  isStreaming?: boolean;
  retryQuestion?: string;
  detailsExpanded?: boolean;
};
type LibraryFolder = { id: string; kind: KnowledgeFolderKind; name: string };

const EMPTY_LIBRARY_HEALTH: KnowledgeLibraryHealthApi = {
  ready_count: 0,
  needs_review_count: 0,
  expired_count: 0,
  needs_reindex_count: 0,
  indexing_count: 0,
  draft_count: 0,
  archived_count: 0,
  open_gaps: [],
};

const workflowStates: WorkflowState[] = ["Needs review", "Approved", "Expired", "Needs re-index", "Archived"];

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
const SUGGESTED_QUESTION_LIMIT = 6;
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
const LOW_CONFIDENCE_THRESHOLD = 0.5;
const NO_KNOWLEDGE_ANSWER =
  "I could not find this information in the uploaded knowledge base.";
const REGENERATE_MORE_SOURCES = 8;
const KNOWLEDGE_CHAT_STORAGE_PREFIX = "bsg:knowledge-chat";
const CHAT_SCROLL_THRESHOLD_PX = 80;

type KnowledgeChatSession = {
  messages: ChatMessage[];
  selectedAgentMessageId: string | null;
};

function createChatMessageId() {
  return crypto.randomUUID();
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
    const parsed = JSON.parse(raw) as KnowledgeChatSession & { selectedAgentMessageIndex?: number | null };
    if (!Array.isArray(parsed.messages)) return null;
    const messages = parsed.messages
      .map(normalizeChatMessage)
      .filter((message): message is ChatMessage => message !== null);
    if (messages.length !== parsed.messages.length) return null;
    let selectedAgentMessageId = parsed.selectedAgentMessageId ?? null;
    if (
      !selectedAgentMessageId &&
      typeof parsed.selectedAgentMessageIndex === "number" &&
      parsed.selectedAgentMessageIndex >= 0 &&
      parsed.selectedAgentMessageIndex < messages.length
    ) {
      selectedAgentMessageId = messages[parsed.selectedAgentMessageIndex]?.id ?? null;
    }
    if (selectedAgentMessageId && !messages.some((message) => message.id === selectedAgentMessageId)) {
      selectedAgentMessageId = null;
    }
    return { messages, selectedAgentMessageId };
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
  messages: ChatMessage[],
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

  const recentCitationTitles: string[] = [];
  for (let i = messages.length - 1; i >= 0 && recentCitationTitles.length < 3; i -= 1) {
    const msg = messages[i];
    if (msg.role !== "agent" || !msg.citations?.length) continue;
    for (const citation of msg.citations) {
      if (!recentCitationTitles.includes(citation.title)) {
        recentCitationTitles.push(citation.title);
      }
    }
  }
  for (const title of recentCitationTitles.slice(0, 2)) {
    add(`Tell me more about "${title}"`);
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

const initialDocuments: KnowledgeDocument[] = [];

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

function agentMessageFromResponse(response: KnowledgeAskResponseApi): ChatMessage {
  return {
    id: createChatMessageId(),
    role: "agent",
    text: response.answer_text,
    next_step: response.next_step,
    confidence_score: response.confidence_score,
    confidence_reasons: response.confidence_reasons,
    structured_answer: response.structured_answer,
    knowledge_gap: response.knowledge_gap,
    citations: response.citations,
    retrieval_debug: response.retrieval_debug ?? null,
    query_id: response.query_id,
    detailsExpanded:
      (response.confidence_score ?? 1) < LOW_CONFIDENCE_THRESHOLD || !!response.knowledge_gap,
  };
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

function summarizeRegeneration(previous: ChatMessage, next: ChatMessage): string {
  const previousTitles = new Set((previous.citations ?? []).map((item) => item.title));
  const nextTitles = new Set((next.citations ?? []).map((item) => item.title));
  const added = [...nextTitles].filter((title) => !previousTitles.has(title));
  const removed = [...previousTitles].filter((title) => !nextTitles.has(title));
  const parts: string[] = [];
  if (added.length > 0) parts.push(`Added ${added.length} source${added.length === 1 ? "" : "s"}`);
  if (removed.length > 0) parts.push(`Removed ${removed.length} source${removed.length === 1 ? "" : "s"}`);
  if (previous.confidence_score !== undefined && next.confidence_score !== undefined) {
    const delta = Math.round((next.confidence_score - previous.confidence_score) * 100);
    if (delta !== 0) parts.push(`Confidence ${delta > 0 ? "+" : ""}${delta} pts`);
  }
  if (parts.length === 0) return "Regenerated with the same visible source set";
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

function isInteractiveChatTarget(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest("button, textarea, a, input, select"));
}

function KnowledgePage() {
  const user = useAuthStore((s) => s.user);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>(initialDocuments);
  const [libraryFolders, setLibraryFolders] = useState<LibraryFolder[]>([]);
  const [loadingFolders, setLoadingFolders] = useState(true);
  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);
  const [createFolderName, setCreateFolderName] = useState("");
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [createFolderError, setCreateFolderError] = useState("");
  const [docId, setDocId] = useState<string | null>(null);
  const [activeChunkId, setActiveChunkId] = useState<string | null>(null);
  const [documentTab, setDocumentTab] = useState("preview");
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [loadingDocDetail, setLoadingDocDetail] = useState(false);
  const [docsLoadError, setDocsLoadError] = useState("");
  const [askInput, setAskInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [animatingMessageId, setAnimatingMessageId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedAgentMessageId, setSelectedAgentMessageId] = useState<string | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [liveAnnouncement, setLiveAnnouncement] = useState("");
  const [showJumpToBottom, setShowJumpToBottom] = useState(false);
  const [retrievalScope, setRetrievalScope] = useState<KnowledgeRetrievalSettingsApi | null>(null);
  const [scopeDraft, setScopeDraft] = useState<KnowledgeRetrievalSettingsApi | null>(null);
  const [savingScope, setSavingScope] = useState(false);
  const [queryHistory, setQueryHistory] = useState<AgentQueryApi[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [evalMetrics, setEvalMetrics] = useState<KnowledgeEvalMetricsApi | null>(null);
  const [evalQuestions, setEvalQuestions] = useState<KnowledgeEvalQuestionApi[]>([]);
  const [loadingEval, setLoadingEval] = useState(false);
  const [runningEval, setRunningEval] = useState(false);
  const [lastEvalRun, setLastEvalRun] = useState<KnowledgeEvalRunApi | null>(null);
  const [evalQuestionText, setEvalQuestionText] = useState("");
  const [evalExpectedDocId, setEvalExpectedDocId] = useState("");
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
  const [libraryHealth, setLibraryHealth] = useState<KnowledgeLibraryHealthApi>(EMPTY_LIBRARY_HEALTH);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [activeFolder, setActiveFolder] = useState<string | "All">("All");
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | "All">("All");
  const [workflowFilter, setWorkflowFilter] = useState<WorkflowState | "All">("All");
  const [sortMode, setSortMode] = useState<SortMode>("recent");
  const [healthFilter, setHealthFilter] = useState<HealthFilter>("all");
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
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

  const libraryLoading = loadingDocs || loadingFolders;
  const selectedAgentMessage =
    selectedAgentMessageId != null
      ? messages.find((message) => message.id === selectedAgentMessageId) ?? null
      : null;
  const sidebarSources =
    selectedAgentMessage?.role === "agent" ? selectedAgentMessage.citations ?? [] : [];
  const sidebarConfidence = selectedAgentMessage?.confidence_score ?? null;
  const selectedDoc = documents.find((item) => item.id === docId) ?? null;
  const approvedIndexedDocs = documents.filter(isRetrievalReady);
  const canAsk = approvedIndexedDocs.length > 0;
  const suggestedQuestions = useMemo(
    () => buildSuggestedQuestions(documents, libraryFolders, messages),
    [documents, libraryFolders, messages],
  );
  const retrievalScopeLabel = useMemo(
    () => formatRetrievalScopeLabel(retrievalScope),
    [retrievalScope],
  );
  const canAdjustScope = user?.role === "bsg_leadership" || user?.role === "super_admin";
  const draftCount = documents.filter((item) => item.status === "Draft").length;
  const indexingCount = documents.filter((item) => item.indexing).length;
  const archivedCount = documents.filter((item) => item.status === "Archived").length;
  const expiredCount = documents.filter((item) => item.workflowState === "Expired").length;
  const needsReindexCount = documents.filter((item) => item.workflowState === "Needs re-index").length;
  const healthFilters = [
    { id: "all" as const, label: "All", count: documents.length },
    { id: "ready" as const, label: "Ready", count: approvedIndexedDocs.length },
    { id: "needs_approval" as const, label: "Needs approval", count: draftCount },
    { id: "expired" as const, label: "Expired", count: libraryHealth.expired_count || expiredCount },
    { id: "needs_reindex" as const, label: "Needs re-index", count: libraryHealth.needs_reindex_count || needsReindexCount },
    { id: "indexing" as const, label: "Indexing", count: indexingCount },
    { id: "archived" as const, label: "Archived", count: archivedCount },
  ];
  const libraryTodos = libraryHealth.open_gaps;
  const hasLibraryTodos =
    libraryTodos.length > 0 ||
    (libraryHealth.expired_count || expiredCount) > 0 ||
    (libraryHealth.needs_reindex_count || needsReindexCount) > 0 ||
    (!canAsk && documents.length > 0);

  const activeFilterCount = [
    activeFolder !== "All",
    statusFilter !== "All",
    workflowFilter !== "All",
    sortMode !== "recent",
  ].filter(Boolean).length;

  const clearLibraryFilters = () => {
    setActiveFolder("All");
    setStatusFilter("All");
    setWorkflowFilter("All");
    setSortMode("recent");
  };

  const filteredDocuments = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    const filtered = documents.filter((item) => {
      const matchesFolder = activeFolder === "All" || item.folderId === activeFolder;
      const matchesStatus = statusFilter === "All" || item.status === statusFilter;
      const matchesWorkflow = workflowFilter === "All" || item.workflowState === workflowFilter;
      const matchesHealth =
        healthFilter === "all" ||
        (healthFilter === "ready" && isRetrievalReady(item)) ||
        (healthFilter === "needs_approval" && item.status === "Draft") ||
        (healthFilter === "expired" && item.workflowState === "Expired") ||
        (healthFilter === "needs_reindex" && item.workflowState === "Needs re-index") ||
        (healthFilter === "indexing" && item.indexing) ||
        (healthFilter === "archived" && item.status === "Archived");
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
      if (sortMode === "title") return left.title.localeCompare(right.title);
      if (sortMode === "approved") {
        const rankDelta = statusRank[left.status] - statusRank[right.status];
        return rankDelta || left.title.localeCompare(right.title);
      }
      if (sortMode === "indexed") {
        const indexedDelta = Number(right.indexed) - Number(left.indexed);
        return indexedDelta || left.title.localeCompare(right.title);
      }
      const leftTime = Date.parse(left.effectiveDate || "") || 0;
      const rightTime = Date.parse(right.effectiveDate || "") || 0;
      return rightTime - leftTime || left.title.localeCompare(right.title);
    });
  }, [activeFolder, documents, healthFilter, searchTerm, sortMode, statusFilter, workflowFilter]);

  const groupedDocuments = useMemo(
    () =>
      libraryFolders
        .filter((folder) => activeFolder === "All" || folder.id === activeFolder)
        .map((folder) => ({
          id: folder.id,
          kind: folder.kind,
          folderName: folder.name,
          items: filteredDocuments.filter((item) => item.folderId === folder.id),
          total: documents.filter((item) => item.folderId === folder.id).length,
        })),
    [activeFolder, documents, filteredDocuments, libraryFolders],
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
      setLoadingFolders(true);
      setDocsLoadError("");
      try {
        const { folders, documents, library_health } = await getKnowledgeBootstrap();
        setLibraryFolders(
          folders.map((row) => ({
            id: row.id,
            kind: row.folder_kind,
            name: row.name,
          })),
        );
        const mapped = documents.map(documentFromApi);
        setDocuments(mapped);
        setLibraryHealth(library_health ?? EMPTY_LIBRARY_HEALTH);
        setDocId((current) => (current && mapped.some((item) => item.id === current) ? current : mapped[0]?.id ?? null));
      } catch (err) {
        setDocuments([]);
        setLibraryFolders([]);
        setLibraryHealth(EMPTY_LIBRARY_HEALTH);
        setDocId(null);
        setDocsLoadError(err instanceof Error ? err.message : "Could not load knowledge documents.");
      } finally {
        setLoadingDocs(false);
        setLoadingFolders(false);
      }
    };
    void load();
  }, []);

  useEffect(() => {
    if (libraryFolders.length === 0) return;
    setForm((current) => (current.folderId ? current : { ...current, folderId: libraryFolders[0].id }));
    setCollapsedFolders((current) => (current.size > 0 ? current : new Set(libraryFolders.map((folder) => folder.id))));
  }, [libraryFolders]);

  useEffect(() => {
    if (!user?.id) {
      setRetrievalScope(null);
      setScopeDraft(null);
      return;
    }
    void getKnowledgeRetrievalSettings()
      .then((settings) => {
        setRetrievalScope(settings);
        setScopeDraft(settings);
      })
      .catch(() => {
        setRetrievalScope(null);
        setScopeDraft(null);
      });
  }, [user?.id]);

  useEffect(() => {
    if (!user?.id) {
      setQueryHistory([]);
      return;
    }
    setLoadingHistory(true);
    void listAgentQueries(30)
      .then((rows) =>
        setQueryHistory(rows.filter((row) => row.agent_name === "operational_knowledge_agent")),
      )
      .catch(() => setQueryHistory([]))
      .finally(() => setLoadingHistory(false));
  }, [user?.id, messages.length]);

  useEffect(() => {
    if (!user?.id) {
      setEvalMetrics(null);
      setEvalQuestions([]);
      return;
    }
    setLoadingEval(true);
    void Promise.all([getKnowledgeEvalMetrics(30), listKnowledgeEvalQuestions()])
      .then(([metrics, questions]) => {
        setEvalMetrics(metrics);
        setEvalQuestions(questions);
      })
      .catch(() => {
        setEvalMetrics(null);
        setEvalQuestions([]);
      })
      .finally(() => setLoadingEval(false));
  }, [user?.id, messages.length]);

  useEffect(() => {
    if (!selectedDoc || !isDocumentOpen) return;
    let cancelled = false;
    setLoadingDocDetail(true);
    void getKnowledgeDocument(selectedDoc.id)
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
  }, [isDocumentOpen, selectedDoc?.id]);

  useEffect(() => {
    if (!selectedDoc || !isDocumentOpen) return;
    void listKnowledgeDocumentVersions(selectedDoc.id)
      .then(setVersions)
      .catch(() => setVersions([]));
    setVersionCompare(null);
    setCompareLeftId("");
    setCompareRightId("");
  }, [isDocumentOpen, selectedDoc?.id]);

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

  const finishAgentAnswer = (messageId: string, text: string) => {
    const displayText = text.trim();
    if (!displayText) {
      announceAgentMessage(NO_KNOWLEDGE_ANSWER);
      return;
    }
    if (shouldAnimateAnswer(displayText)) {
      setAnimatingMessageId(messageId);
      return;
    }
    announceAgentMessage(displayText);
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
    setSelectedAgentMessageId(stored?.selectedAgentMessageId ?? null);
    setAnimatingMessageId(null);
  }, [user?.id]);

  useEffect(() => {
    const userId = user?.id;
    if (!userId || chatHydratedUserIdRef.current !== userId) return;
    if (messages.length === 0) {
      clearKnowledgeChatSession(userId);
      return;
    }
    saveKnowledgeChatSession(userId, { messages, selectedAgentMessageId });
  }, [user?.id, messages, selectedAgentMessageId]);

  useEffect(() => {
    if (!isDocumentOpen || !activeChunkId || documentTab !== "chunks") return;
    window.setTimeout(() => {
      document.getElementById(`chunk-${activeChunkId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
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
      const row = await uploadKnowledgeDocument(file, apiFields);
      const newDocument = documentFromApi(row);
      setDocuments((current) => {
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

  const syncDocument = (mapped: KnowledgeDocument) => {
    setDocuments((current) => current.map((item) => (item.id === mapped.id ? mapped : item)));
  };

  const updateDocument = async (id: string, patch: Partial<KnowledgeDocument>) => {
    const current = documents.find((item) => item.id === id);
    if (!current) return;
    const optimistic = { ...current, ...patch };
    setDocuments((rows) => rows.map((item) => (item.id === id ? optimistic : item)));
    try {
      const apiPatch = documentToApiPatch(patch);
      const cleaned = Object.fromEntries(
        Object.entries(apiPatch).filter(([, value]) => value !== undefined),
      ) as Record<string, string>;
      const row = await updateKnowledgeDocument(id, cleaned);
      syncDocument(documentFromApi(row));
    } catch {
      setDocuments((rows) => rows.map((item) => (item.id === id ? current : item)));
    }
  };

  const renameDocument = async (document: KnowledgeDocument) => {
    const title = window.prompt("Rename document", document.title)?.trim();
    if (title) await updateDocument(document.id, { title });
  };

  const deleteDocument = async (document: KnowledgeDocument) => {
    const previous = documents;
    setDocuments((current) => current.filter((item) => item.id !== document.id));
    setDocId((current) => (current === document.id ? previous.find((item) => item.id !== document.id)?.id ?? null : current));
    setIsDocumentOpen(false);
    try {
      await deleteKnowledgeDocument(document.id);
    } catch {
      setDocuments(previous);
    }
  };

  const reindexDocument = async (document: KnowledgeDocument) => {
    setDocuments((rows) =>
      rows.map((item) =>
        item.id === document.id
          ? { ...item, indexed: false, indexing: true, processingStatus: "embedding", processingLabel: "Generating Embeddings..." }
          : item,
      ),
    );
    try {
      const row = await reindexKnowledgeDocument(document.id);
      syncDocument(documentFromApi(row));
    } catch {
      setDocuments((rows) =>
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

  const submitAsk = async (
    questionOverride?: string,
    options?: { skipUserMessage?: boolean; maxSources?: number },
  ) => {
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
    setSelectedAgentMessageId(agentMsgId);

    let gotDone = false;
    let streamAnswer = "";
    const askOptions = {
      conversationHistory,
      answerMode: inferAnswerMode(question),
      maxSources: options?.maxSources,
    };

    try {
      for await (const event of streamKnowledgeAsk(question, askOptions)) {
        if (event.type === "meta") {
          setMessages((current) =>
            current.map((msg) =>
              msg.id === agentMsgId
                ? { ...msg, citations: event.citations as ChatMessage["citations"], query_id: event.query_id ?? null }
                : msg,
            ),
          );
        } else if (event.type === "delta") {
          streamAnswer += event.text;
        } else if (event.type === "replace") {
          streamAnswer = event.text;
        } else if (event.type === "done") {
          gotDone = true;
          streamAnswer = event.answer_text?.trim() || streamAnswer;
          const resolvedText = resolveAgentAnswerText(
            { text: streamAnswer, structured_answer: event.structured_answer, next_step: event.next_step },
            event.answer_text,
          );
          setMessages((current) =>
            current.map((msg) => {
              if (msg.id !== agentMsgId) return msg;
              const sa = event.structured_answer;
              return {
                ...msg,
                text: resolvedText,
                isStreaming: false,
                query_id: event.query_id,
                confidence_score: event.confidence_score,
                confidence_reasons: event.confidence_reasons,
                next_step: event.next_step || undefined,
                structured_answer: sa ?? null,
                citations: msg.citations,
                retrieval_debug: event.retrieval_debug ?? null,
                detailsExpanded:
                  (event.confidence_score ?? 1) < LOW_CONFIDENCE_THRESHOLD ? true : msg.detailsExpanded,
              };
            }),
          );
          finishAgentAnswer(agentMsgId, resolvedText);
          if ((event.confidence_score ?? 1) === 0) {
            try {
              const bootstrap = await getKnowledgeBootstrap();
              setLibraryHealth(bootstrap.library_health ?? EMPTY_LIBRARY_HEALTH);
            } catch {
              // library todos refresh is best-effort
            }
          }
        } else if (event.type === "error") {
          setMessages((current) =>
            current.map((msg) =>
              msg.id === agentMsgId
                ? { ...msg, text: "Couldn't reach the agent — retry?", isStreaming: false, isServiceError: true, retryQuestion: question }
                : msg,
            ),
          );
          announceAgentMessage("Couldn't reach the agent — retry?");
        }
      }

      if (!gotDone && !streamAnswer.trim()) {
        const response = await askKnowledgeAgent(question, askOptions);
        const agentMsg = agentMessageFromResponse(response);
        setMessages((current) =>
          current.map((msg) => (msg.id === agentMsgId ? { ...agentMsg, id: agentMsgId, isStreaming: false } : msg)),
        );
        finishAgentAnswer(agentMsgId, agentMsg.text);
      } else if (!gotDone && streamAnswer.trim()) {
        const resolvedText = resolveAgentAnswerText({ text: streamAnswer }, streamAnswer);
        setMessages((current) =>
          current.map((msg) =>
            msg.id === agentMsgId ? { ...msg, text: resolvedText, isStreaming: false } : msg,
          ),
        );
        finishAgentAnswer(agentMsgId, resolvedText);
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
      setMessages((current) =>
        current.map((msg) =>
          msg.id === agentMsgId && msg.isStreaming ? { ...msg, isStreaming: false } : msg,
        ),
      );
      setAsking(false);
    }
  };

  const regenerateAgentAnswer = async (agentMessageId: string, options?: { moreSources?: boolean }) => {
    if (asking || !canAsk) return;
    const agentIndex = messages.findIndex((message) => message.id === agentMessageId);
    if (agentIndex < 0) return;
    const previousAgentMessage = messages[agentIndex];
    const question = findPrecedingUserQuestion(messages, agentMessageId);
    if (!question) return;

    const priorMessages = messages.slice(0, agentIndex);
    const conversationHistory = buildConversationHistory(priorMessages.slice(0, -1));

    followChatScrollRef.current = true;
    setShowJumpToBottom(false);
    setMessages((current) => current.filter((message) => message.id !== agentMessageId));
    setAnimatingMessageId(null);
    setAsking(true);
    try {
      const response = await askKnowledgeAgent(question, {
        conversationHistory,
        answerMode: inferAnswerMode(question),
        maxSources: options?.moreSources ? REGENERATE_MORE_SOURCES : undefined,
      });
      const agentMsg = agentMessageFromResponse(response);
      agentMsg.regenerationSummary = summarizeRegeneration(previousAgentMessage, agentMsg);
      setMessages((current) => {
        const next = [...current];
        next.splice(agentIndex, 0, agentMsg);
        return next;
      });
      setSelectedAgentMessageId(agentMsg.id);
      finishAgentAnswer(agentMsg.id, agentMsg.text);
    } catch {
      const errorMsg: ChatMessage = {
        id: createChatMessageId(),
        role: "agent",
        text: "Couldn't reach the agent — retry?",
        isServiceError: true,
        retryQuestion: question,
      };
      setMessages((current) => {
        const next = [...current];
        next.splice(agentIndex, 0, errorMsg);
        return next;
      });
      announceAgentMessage(errorMsg.text);
    } finally {
      setAsking(false);
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

  const openSavedAnswer = async (query: AgentQueryApi) => {
    if (asking) return;
    setAsking(true);
    try {
      const response = await getKnowledgeQueryAnswer(query.id);
      const userMsg = createUserMessage(query.query_text);
      const agentMsg = agentMessageFromResponse(response);
      agentMsg.detailsExpanded = true;
      setMessages((current) => [...current, userMsg, agentMsg]);
      setSelectedAgentMessageId(agentMsg.id);
      finishAgentAnswer(agentMsg.id, agentMsg.text);
    } catch {
      window.alert("Could not reopen that saved answer.");
    } finally {
      setAsking(false);
    }
  };

  const saveRetrievalScope = async () => {
    if (!scopeDraft || savingScope) return;
    setSavingScope(true);
    try {
      const saved = await updateKnowledgeRetrievalSettings({
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

  const refreshEvalDashboard = async () => {
    const [metrics, questions] = await Promise.all([getKnowledgeEvalMetrics(30), listKnowledgeEvalQuestions()]);
    setEvalMetrics(metrics);
    setEvalQuestions(questions);
  };

  const addEvalQuestion = async () => {
    const question = evalQuestionText.trim();
    if (!question) return;
    try {
      const created = await createKnowledgeEvalQuestion({
        question_text: question,
        expected_document_ids: evalExpectedDocId ? [evalExpectedDocId] : [],
      });
      setEvalQuestions((current) => [created, ...current]);
      setEvalQuestionText("");
      setEvalExpectedDocId("");
      void refreshEvalDashboard();
    } catch {
      window.alert("Could not add that eval question.");
    }
  };

  const toggleEvalQuestion = async (question: KnowledgeEvalQuestionApi) => {
    try {
      const updated = await updateKnowledgeEvalQuestion(question.id, { is_active: !question.is_active });
      setEvalQuestions((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      void refreshEvalDashboard();
    } catch {
      window.alert("Could not update that eval question.");
    }
  };

  const runEvalSet = async () => {
    if (runningEval) return;
    setRunningEval(true);
    try {
      const result = await runKnowledgeEval(50);
      setLastEvalRun(result);
      await refreshEvalDashboard();
    } catch {
      window.alert("Could not run the eval set.");
    } finally {
      setRunningEval(false);
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
    setSelectedAgentMessageId(null);
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
    setDocId(id);
    setActiveChunkId(chunkId);
    setDocumentTab(chunkId ? "chunks" : "preview");
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
      libraryFolders.find((folder) => folder.kind === gap.suggested_folder_kind) ?? libraryFolders[0];
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
    try {
      await resolveKnowledgeGap(gapId);
      setLibraryHealth((current) => ({
        ...current,
        open_gaps: current.open_gaps.filter((gap) => gap.id !== gapId),
      }));
    } catch {
      // keep todo visible if resolve fails
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
      const created = await createKnowledgeFolder({ name });
      await loadLibraryFolders({ silent: true });
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
    if (!selectedDoc || !compareLeftId || !compareRightId || compareLeftId === compareRightId) return;
    try {
      const result = await compareKnowledgeDocumentVersions(selectedDoc.id, compareLeftId, compareRightId);
      setVersionCompare(result);
    } catch {
      setVersionCompare(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 px-1 py-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">Knowledge workspace</h1>
        </div>
        {!libraryLoading && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              className="h-9 gap-2 bg-[color:var(--brand)] text-xs text-[color:var(--brand-foreground)]"
              onClick={() => setIsUploadOpen(true)}
            >
              <Upload className="h-4 w-4" />
              Upload Document
            </Button>
          </div>
        )}
      </div>

      {libraryLoading ? (
        <KnowledgeLoadingScreen />
      ) : (
      <div className="grid grid-cols-12 items-stretch gap-5 xl:h-[calc(100vh-11.5rem)] xl:min-h-[44rem]">
        <div className="col-span-12 flex min-h-0 flex-col gap-5 xl:col-span-4">
          <Card className="shrink-0 border-transparent bg-card/80">
            <div className="border-b border-border/70 px-3 py-2">
              <div className="flex items-center gap-1.5">
                <Sparkles className="h-3 w-3 text-[color:var(--brand)]" />
                <span className="text-xs font-semibold tracking-tight text-foreground">Sources</span>
                {sidebarSources.length > 0 && (
                  <span className="text-[10px] text-muted-foreground">
                    · {sidebarSources.length} for selected answer
                  </span>
                )}
              </div>
            </div>

            {sidebarSources.length === 0 ? (
              <div className="flex items-center gap-2.5 px-3 py-3 text-left">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary/60 text-muted-foreground">
                  <FileText className="h-3.5 w-3.5" />
                </div>
                <p className="text-[11px] leading-4 text-muted-foreground">
                  {selectedAgentMessageId != null
                    ? "No sources cited for this answer."
                    : "Ask a question, then click an answer to view citations."}
                </p>
              </div>
            ) : (
              <div className="max-h-36 space-y-1.5 overflow-y-auto px-2.5 py-2">
                {sidebarSources.map((src, idx) => {
                  const pct = Math.round(src.relevance_score * 100);
                  const isSelected = docId === src.document_id && activeChunkId === src.chunk_id;
                  return (
                    <button
                      key={`${src.document_id}-${idx}`}
                      type="button"
                      onClick={() => openDocumentWithChunk(src.document_id, src.chunk_id, true)}
                      className={cn(
                        "w-full rounded-md border p-2 text-left transition-colors",
                        isSelected
                          ? "border-[color:var(--brand)]/40 bg-[color:var(--brand)]/8"
                          : "border-border/70 bg-secondary/40 hover:bg-secondary/80",
                      )}
                    >
                      <div className="mb-0.5 flex items-start justify-between gap-2">
                        <span className="line-clamp-1 text-[10px] font-semibold leading-tight text-foreground">{src.title}</span>
                        {pct > 0 && (
                          <span className="shrink-0 rounded-sm bg-[color:var(--brand)]/10 px-1 py-0.5 text-[9px] font-semibold text-[color:var(--brand)]">
                            {pct}%
                          </span>
                        )}
                      </div>
                      <div className="text-[9px] text-muted-foreground">
                        {src.source_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                        {src.folder_name ? ` · ${src.folder_name}` : ""}
                        {src.page_number ? ` · p. ${src.page_number}` : ""}
                      </div>
                      {src.chunk_preview && (
                        <p className="mt-1 line-clamp-2 text-[9px] leading-3.5 text-muted-foreground">{src.chunk_preview}</p>
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
            sub={`${documents.length} governed documents`}
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

          {hasLibraryTodos && (
            <div className="space-y-2 rounded-md border border-[color:var(--brand)]/20 bg-[color:var(--brand)]/5 p-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                <AlertTriangle className="h-3.5 w-3.5 text-[color:var(--brand)]" />
                Library health
              </div>
              {!canAsk && (
                <p className="text-[11px] leading-4 text-muted-foreground">
                  The agent has no retrieval-ready sources. Approve and index documents before asking questions.
                </p>
              )}
              <div className="flex flex-wrap gap-1.5">
                {(libraryHealth.expired_count || expiredCount) > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      setHealthFilter("expired");
                      setWorkflowFilter("Expired");
                    }}
                    className="rounded-full border border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 px-2.5 py-1 text-[10px] font-medium text-[color:var(--danger)]"
                  >
                    {libraryHealth.expired_count || expiredCount} expired
                  </button>
                )}
                {(libraryHealth.needs_reindex_count || needsReindexCount) > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      setHealthFilter("needs_reindex");
                      setWorkflowFilter("Needs re-index");
                    }}
                    className="rounded-full border border-border/70 bg-card px-2.5 py-1 text-[10px] font-medium text-foreground"
                  >
                    {libraryHealth.needs_reindex_count || needsReindexCount} need re-index
                  </button>
                )}
                {draftCount > 0 && !canAsk && (
                  <button
                    type="button"
                    onClick={() => setHealthFilter("needs_approval")}
                    className="rounded-full border border-border/70 bg-card px-2.5 py-1 text-[10px] font-medium text-foreground"
                  >
                    {draftCount} awaiting approval
                  </button>
                )}
              </div>
              {libraryTodos.length > 0 && (
                <div className="space-y-2 border-t border-border/50 pt-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Knowledge gaps
                  </p>
                  {libraryTodos.slice(0, 5).map((gap) => (
                    <div key={gap.id} className="rounded-md border border-border/60 bg-card/80 p-2">
                      <p className="text-[11px] font-medium text-foreground">{gap.query_text}</p>
                      <p className="mt-0.5 text-[10px] text-muted-foreground">{gap.message}</p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 text-[10px]"
                          onClick={() => prefillUploadFromGap(gap)}
                        >
                          Upload related doc
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          className="h-7 text-[10px]"
                          onClick={() => void handleResolveGap(gap.id)}
                        >
                          Mark resolved
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
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
                    <Select value={activeFolder} onValueChange={(value) => setActiveFolder(value)}>
                      <SelectTrigger className="h-8 text-xs shadow-none"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="All">All folders</SelectItem>
                        {libraryFolders.map((folder) => (
                          <SelectItem key={folder.id} value={folder.id}>{folder.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Status">
                    <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as DocumentStatus | "All")}>
                      <SelectTrigger className="h-8 text-xs shadow-none"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="All">All statuses</SelectItem>
                        {statuses.map((status) => (
                          <SelectItem key={status} value={status}>{status}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Workflow">
                    <Select value={workflowFilter} onValueChange={(value) => setWorkflowFilter(value as WorkflowState | "All")}>
                      <SelectTrigger className="h-8 text-xs shadow-none"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="All">All workflow states</SelectItem>
                        {workflowStates.map((state) => (
                          <SelectItem key={state} value={state}>{state}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Sort by">
                    <Select value={sortMode} onValueChange={(value) => setSortMode(value as SortMode)}>
                      <SelectTrigger className="h-8 text-xs shadow-none"><SelectValue /></SelectTrigger>
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
            <>
            {groupedDocuments.map((group) => {
              const isCollapsed = collapsedFolders.has(group.id);
              const isExpanded = expandedFolders.has(group.id);
              const visibleItems = isExpanded ? group.items : group.items.slice(0, folderPreviewLimit);
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
                              <p className="truncate text-sm font-medium text-foreground">{item.title}</p>
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
                            {item.qualityScore && <QualityScoreBadge score={item.qualityScore} />}
                            {item.semanticRelevance != null && item.semanticRelevance > 0 && (
                              <span className="rounded bg-[color:var(--brand)]/10 px-1.5 py-0.5 text-[9px] font-medium text-[color:var(--brand)]">
                                {Math.round(item.semanticRelevance * 100)}% match
                              </span>
                            )}
                            {item.indexing && <DocBadge label={item.processingLabel} tone="info" />}
                            {item.processingStatus === "ready" && <DocBadge label="Ready" tone="success" />}
                            {item.processingStatus === "failed" && <DocBadge label="Failed" tone="danger" />}
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
                      {isExpanded ? "Show less" : `Show all ${group.items.length} documents${hiddenCount ? ` (${hiddenCount} more)` : ""}`}
                    </button>
                  )}
                </div>
              </section>
              );
            })}
            {filteredDocuments.length === 0 && libraryFolders.length === 0 && !docsLoadError && (
              <div className="rounded-md border border-dashed border-border/70 bg-secondary/30 p-6 text-center text-xs text-muted-foreground">
                No folders yet. Use <span className="font-medium text-foreground">Create</span> to add your first folder.
              </div>
            )}
            {filteredDocuments.length === 0 && libraryFolders.length > 0 && (
              <div className="rounded-md bg-secondary/50 p-6 text-center text-xs text-muted-foreground">
                {documents.length === 0 && !docsLoadError ? (
                  <span>
                    No documents are visible for {user?.organisation?.name ?? "your organisation"}.
                    {user?.role === "client" ? " Client accounts cannot access the knowledge library API." : " Try the PM dev account (pm@bsg.dev) or upload a new document."}
                  </span>
                ) : (
                  "No documents match the current filters."
                )}
              </div>
            )}
            </>
          </div>
        </Card>
        </div>

        <div className="col-span-12 min-h-0 xl:col-span-8">
          <Card className="flex h-full min-h-0 flex-col border-transparent bg-card/80 p-0">
            <div className="border-b border-border/70 px-5 py-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[color:var(--brand)] text-[color:var(--brand-foreground)]">
                      <Bot className="h-4 w-4" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold tracking-tight text-foreground">Ask Knowledge Agent</h3>
                      <p className="mt-0.5 text-xs text-muted-foreground">Answers use approved, ready documents only.</p>
                      {retrievalScopeLabel && (
                        <span className="mt-1.5 inline-flex rounded-full border border-[color:var(--brand)]/25 bg-[color:var(--brand)]/8 px-2.5 py-0.5 text-[10px] font-medium text-[color:var(--brand)]">
                          {retrievalScopeLabel}
                        </span>
                      )}
                      {canAdjustScope && scopeDraft && (
                        <Popover>
                          <PopoverTrigger asChild>
                            <button
                              type="button"
                              className="mt-1.5 inline-flex rounded-full border border-border/70 px-2.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                            >
                              Adjust scope
                            </button>
                          </PopoverTrigger>
                          <PopoverContent align="start" className="w-80 space-y-3 p-3">
                            <div>
                              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Retrieval scope</div>
                              <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                                Applies to future Knowledge Agent answers.
                              </p>
                            </div>
                            <div className="space-y-2">
                              <label className="block text-[11px] font-medium text-muted-foreground">
                                Project
                                <Input
                                  value={scopeDraft.project ?? ""}
                                  onChange={(event) => setScopeDraft((current) => current ? { ...current, project: event.target.value } : current)}
                                  placeholder="All projects"
                                  className="mt-1 h-8 text-xs"
                                />
                              </label>
                              <label className="block text-[11px] font-medium text-muted-foreground">
                                Department
                                <Input
                                  value={scopeDraft.department ?? ""}
                                  onChange={(event) => setScopeDraft((current) => current ? { ...current, department: event.target.value } : current)}
                                  placeholder="All departments"
                                  className="mt-1 h-8 text-xs"
                                />
                              </label>
                              <div className="grid grid-cols-2 gap-2">
                                <label className="block text-[11px] font-medium text-muted-foreground">
                                  Max sources
                                  <Input
                                    type="number"
                                    min={1}
                                    max={10}
                                    value={scopeDraft.max_sources}
                                    onChange={(event) => setScopeDraft((current) => current ? { ...current, max_sources: Number(event.target.value) } : current)}
                                    className="mt-1 h-8 text-xs"
                                  />
                                </label>
                                <label className="block text-[11px] font-medium text-muted-foreground">
                                  Min relevance
                                  <Input
                                    type="number"
                                    min={0}
                                    max={1}
                                    step={0.05}
                                    value={scopeDraft.min_confidence}
                                    onChange={(event) => setScopeDraft((current) => current ? { ...current, min_confidence: Number(event.target.value) } : current)}
                                    className="mt-1 h-8 text-xs"
                                  />
                                </label>
                              </div>
                              <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                <input
                                  type="checkbox"
                                  checked={scopeDraft.include_histories}
                                  onChange={(event) => setScopeDraft((current) => current ? { ...current, include_histories: event.target.checked } : current)}
                                />
                                Include histories and lessons learned
                              </label>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              disabled={savingScope}
                              className="h-8 w-full text-xs"
                              onClick={() => void saveRetrievalScope()}
                            >
                              {savingScope ? "Saving..." : "Save scope"}
                            </Button>
                          </PopoverContent>
                        </Popover>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={asking}
                        className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
                      >
                        <Sparkles className="h-3.5 w-3.5" />
                        Eval
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-[360px] space-y-3 p-3">
                      <div>
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Evaluation & observability
                        </div>
                        <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                          Last {evalMetrics?.days ?? 30} days of Knowledge Agent traffic.
                        </p>
                      </div>
                      {loadingEval ? (
                        <p className="text-xs text-muted-foreground">Loading eval metrics...</p>
                      ) : (
                        <div className="grid grid-cols-2 gap-2">
                          <InfoTile label="Citation hit" value={`${Math.round((evalMetrics?.citation_hit_rate ?? 0) * 100)}%`} />
                          <InfoTile label="Empty answers" value={`${Math.round((evalMetrics?.empty_answer_rate ?? 0) * 100)}%`} />
                          <InfoTile label="Latency p95" value={evalMetrics?.latency_p95_ms ? `${evalMetrics.latency_p95_ms}ms` : "N/A"} />
                          <InfoTile label="Downvotes" value={`${Math.round((evalMetrics?.downvote_rate ?? 0) * 100)}%`} />
                        </div>
                      )}
                      <div className="rounded-md border border-border/60 bg-secondary/25 p-2">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                            Gold Q&A set
                          </span>
                          <span className="text-[10px] text-muted-foreground">
                            {evalMetrics?.eval_question_count ?? evalQuestions.filter((item) => item.is_active).length} active
                          </span>
                        </div>
                        {canAdjustScope && (
                          <div className="mb-2 space-y-1.5">
                            <Input
                              value={evalQuestionText}
                              onChange={(event) => setEvalQuestionText(event.target.value)}
                              placeholder="Question expected to cite a source"
                              className="h-8 text-xs"
                            />
                            <Select value={evalExpectedDocId || "none"} onValueChange={(value) => setEvalExpectedDocId(value === "none" ? "" : value)}>
                              <SelectTrigger className="h-8 text-xs">
                                <SelectValue placeholder="Expected source" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="none">No expected source</SelectItem>
                                {approvedIndexedDocs.slice(0, 50).map((doc) => (
                                  <SelectItem key={doc.id} value={doc.id}>{doc.title}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <Button
                              type="button"
                              size="sm"
                              className="h-8 w-full text-xs"
                              disabled={!evalQuestionText.trim()}
                              onClick={() => void addEvalQuestion()}
                            >
                              Add gold question
                            </Button>
                          </div>
                        )}
                        <div className="max-h-32 space-y-1 overflow-y-auto">
                          {evalQuestions.length === 0 ? (
                            <p className="text-[11px] text-muted-foreground">No gold questions yet.</p>
                          ) : (
                            evalQuestions.slice(0, 6).map((question) => (
                              <div key={question.id} className="flex items-start justify-between gap-2 rounded-sm bg-card/70 px-2 py-1.5">
                                <span className={cn("line-clamp-2 text-[11px] leading-4", !question.is_active && "text-muted-foreground line-through")}>
                                  {question.question_text}
                                </span>
                                {canAdjustScope && (
                                  <button
                                    type="button"
                                    className="shrink-0 text-[10px] text-muted-foreground hover:text-foreground"
                                    onClick={() => void toggleEvalQuestion(question)}
                                  >
                                    {question.is_active ? "Disable" : "Enable"}
                                  </button>
                                )}
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                      {canAdjustScope && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={runningEval || evalQuestions.every((item) => !item.is_active)}
                          className="h-8 w-full text-xs"
                          onClick={() => void runEvalSet()}
                        >
                          {runningEval ? "Running eval..." : "Run active eval set"}
                        </Button>
                      )}
                      {lastEvalRun && (
                        <p className="text-[11px] leading-4 text-muted-foreground">
                          Last run: {lastEvalRun.run_count} questions, {Math.round(lastEvalRun.citation_hit_rate * 100)}% citation hit, {Math.round(lastEvalRun.empty_answer_rate * 100)}% empty.
                        </p>
                      )}
                    </PopoverContent>
                  </Popover>
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={asking}
                        className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
                      >
                        <History className="h-3.5 w-3.5" />
                        History
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-80 p-2">
                      <div className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Recent knowledge answers
                      </div>
                      {loadingHistory ? (
                        <p className="px-1 py-2 text-xs text-muted-foreground">Loading saved answers...</p>
                      ) : queryHistory.length === 0 ? (
                        <p className="px-1 py-2 text-xs text-muted-foreground">No saved answers yet.</p>
                      ) : (
                        <div className="max-h-72 space-y-1 overflow-y-auto">
                          {queryHistory.slice(0, 12).map((query) => (
                            <button
                              key={query.id}
                              type="button"
                              disabled={asking}
                              onClick={() => void openSavedAnswer(query)}
                              className="w-full rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-secondary disabled:opacity-50"
                            >
                              <span className="line-clamp-2 font-medium text-foreground">{query.query_text}</span>
                              <span className="mt-0.5 block text-[10px] text-muted-foreground">
                                {new Date(query.created_at).toLocaleString()}
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </PopoverContent>
                  </Popover>
                  <span className="rounded-full bg-[color:var(--success)]/10 px-2.5 py-1 text-[10px] font-medium text-[color:var(--success)]">
                    {approvedIndexedDocs.length} sources ready
                  </span>
                  {sidebarConfidence != null && (
                    <AiBadge confidence={Math.round(sidebarConfidence * 100)} />
                  )}
                  {(messages.length > 0 || selectedAgentMessageId != null) && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={asking}
                      className="h-8 gap-1.5 px-2 text-xs text-muted-foreground"
                      onClick={clearConversation}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Clear conversation
                    </Button>
                  )}
                </div>
              </div>
            </div>

            <div className="relative mx-5 mt-4 min-h-0 flex-1">
              <div
                ref={chatScrollRef}
                onScroll={handleChatScroll}
                className="h-full space-y-4 overflow-y-auto rounded-md bg-secondary/35 p-4 text-xs"
              >
              <div className="sr-only" aria-live="polite" aria-atomic="true">
                {liveAnnouncement}
              </div>
              {messages.length === 0 && !asking ? (
                <div className="flex h-full min-h-[220px] flex-col items-center justify-center px-2 py-6 text-center">
                  <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-card text-[color:var(--brand)]">
                    <Sparkles className="h-5 w-5" />
                  </div>
                  <p className="text-sm font-medium text-foreground">
                    {canAsk ? "Ask about SOPs, guides, or past issues" : "Upload and approve documents first"}
                  </p>
                  <p className="mt-1 max-w-sm text-[11px] leading-4 text-muted-foreground">
                    {canAsk
                      ? "Answers are grounded in approved, indexed documents from your knowledge library."
                      : `No retrieval-ready sources yet (${approvedIndexedDocs.length} ready). Upload a document, set owner and effective date, approve it, and wait for indexing.`}
                  </p>
                  {!canAsk && (
                    <div className="mt-3 max-w-sm space-y-1 text-left text-[11px] text-muted-foreground">
                      {draftCount > 0 && <p>• Approve {draftCount} draft document{draftCount === 1 ? "" : "s"}</p>}
                      {needsReindexCount > 0 && <p>• Re-index {needsReindexCount} document{needsReindexCount === 1 ? "" : "s"} stuck in processing</p>}
                      {expiredCount > 0 && <p>• Review {expiredCount} expired SOP{expiredCount === 1 ? "" : "s"}</p>}
                      {documents.length === 0 && <p>• Upload your first SOP or guide using the library panel</p>}
                    </div>
                  )}
                  <div className="mt-5 flex max-w-md flex-wrap justify-center gap-2">
                    {canAsk && suggestedQuestions.length > 0 ? (
                      suggestedQuestions.map((question) => (
                        <button
                          key={question}
                          type="button"
                          onClick={() => void submitAsk(question)}
                          className="rounded-full border border-border/70 bg-card px-3 py-1.5 text-left text-[11px] text-muted-foreground transition-colors hover:border-[color:var(--brand)]/30 hover:bg-secondary/70 hover:text-foreground"
                        >
                          {question}
                        </button>
                      ))
                    ) : (
                      <p className="text-[11px] text-muted-foreground">
                        {canAsk
                          ? "Upload and approve documents to see suggested questions."
                          : "Use Upload Document in the library, then approve and index it."}
                      </p>
                    )}
                  </div>
                </div>
              ) : (
              messages.map((message) => {
                const isAnimating = message.role === "agent" && message.id === animatingMessageId;
                const isAgentReply = message.role === "agent" && !message.isServiceError && !message.isStreaming;
                const showPostAnimationActions = isAgentReply && !isAnimating;
                const showAgentDetails = isAgentReply && !isAnimating;
                const detailsOpen = isAgentReply && isMessageDetailsOpen(message);
                const showCollapsibleDetails = showAgentDetails && hasCollapsibleDetails(message);
                const isSelectedAgent = message.role === "agent" && message.id === selectedAgentMessageId;
                const isSelectableAgent = message.role === "agent" && !message.isServiceError;

                return (
                <div
                  key={message.id}
                  className={cn(
                    "flex gap-3",
                    message.role === "user"
                      ? "justify-end"
                      : "justify-start",
                  )}
                >
                  {message.role === "agent" && (
                    <div
                      className={cn(
                        "mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground",
                        message.isServiceError && "text-[color:var(--danger)]",
                      )}
                    >
                      <Bot className="h-3.5 w-3.5" />
                    </div>
                  )}
                  <div
                    role={isSelectableAgent ? "button" : undefined}
                    tabIndex={isSelectableAgent ? 0 : undefined}
                    onClick={
                      isSelectableAgent
                        ? (event) => {
                            if (isInteractiveChatTarget(event.target)) return;
                            setSelectedAgentMessageId(message.id);
                          }
                        : undefined
                    }
                    onKeyDown={
                      isSelectableAgent
                        ? (event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedAgentMessageId(message.id);
                            }
                          }
                        : undefined
                    }
                    className={cn(
                      "max-w-[88%] rounded-md px-3 py-3",
                      message.role === "user"
                        ? "bg-[color:var(--brand)] text-[color:var(--brand-foreground)]"
                        : message.isServiceError
                          ? "border border-[color:var(--danger)]/30 bg-[color:var(--danger)]/5"
                          : "bg-card",
                      isSelectableAgent && "cursor-pointer transition-shadow hover:shadow-sm",
                      isSelectedAgent && "ring-2 ring-[color:var(--brand)]/35",
                    )}
                  >
                    <div className={cn("mb-1 flex items-center justify-between gap-2 text-[10px] font-semibold uppercase tracking-wider", message.role === "user" ? "text-white/70" : "text-muted-foreground")}>
                      <span>
                        {message.role === "user"
                          ? "You"
                          : message.isServiceError
                            ? "Service error"
                            : "Knowledge Agent"}
                      </span>
                      <div className="flex items-center gap-1.5 normal-case">
                        {isAnimating && (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setAnimatingMessageId(null);
                              announceAgentMessage(message.text);
                            }}
                            className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-secondary/70 hover:text-foreground"
                          >
                            Skip
                          </button>
                        )}
                        {isAgentReply && message.confidence_score !== undefined && message.confidence_score > 0 && (
                          <span className="rounded-sm bg-[color:var(--success)]/15 px-1.5 py-0.5 text-[color:var(--success)]">
                            {Math.round(message.confidence_score * 100)}% confidence
                          </span>
                        )}
                      </div>
                    </div>
                    {isAnimating ? (
                      <TypewriterText
                        text={message.text}
                        className="leading-5"
                        onProgress={() => scrollChatToEnd()}
                        onComplete={() => {
                          setAnimatingMessageId(null);
                          announceAgentMessage(message.text);
                        }}
                      />
                    ) : message.isStreaming ? (
                      <TypingIndicator />
                    ) : (
                      <p className={cn("leading-5", message.isServiceError && "text-foreground")}>
                        {buildAgentDisplayText(message) || NO_KNOWLEDGE_ANSWER}
                      </p>
                    )}
                    {showPostAnimationActions && (
                      <div className="relative z-10 mt-2.5 flex flex-wrap items-center gap-1 border-t border-border/50 pt-2">
                        <button
                          type="button"
                          disabled={asking}
                          onClick={(event) => {
                            event.stopPropagation();
                            void copyAgentAnswer(message.id, message.text);
                          }}
                          className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-secondary/70 hover:text-foreground disabled:opacity-50"
                        >
                          {copiedMessageId === message.id ? (
                            <>
                              <CheckCircle2 className="h-3 w-3 text-[color:var(--success)]" />
                              Copied
                            </>
                          ) : (
                            <>
                              <Copy className="h-3 w-3" />
                              Copy
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          disabled={asking || !canAsk}
                          onClick={(event) => {
                            event.stopPropagation();
                            void regenerateAgentAnswer(message.id);
                          }}
                          className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-secondary/70 hover:text-foreground disabled:opacity-50"
                        >
                          <RefreshCw className="h-3 w-3" />
                          Regenerate
                        </button>
                        <button
                          type="button"
                          disabled={asking || !canAsk}
                          onClick={(event) => {
                            event.stopPropagation();
                            void regenerateAgentAnswer(message.id, { moreSources: true });
                          }}
                          className="inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-secondary/70 hover:text-foreground disabled:opacity-50"
                          title="Regenerate with more source documents"
                        >
                          More sources
                        </button>
                        <span className="mx-0.5 h-3 w-px bg-border/70" aria-hidden="true" />
                        <button
                          type="button"
                          onClick={() => void setMessageFeedback(message.id, "up")}
                          className={cn(
                            "inline-flex cursor-pointer items-center rounded-sm p-1 transition-colors",
                            message.feedback === "up"
                              ? "bg-[color:var(--success)]/20 text-[color:var(--success)] ring-1 ring-[color:var(--success)]/40"
                              : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground",
                          )}
                          title="Helpful answer"
                          aria-label="Helpful answer"
                          aria-pressed={message.feedback === "up"}
                        >
                          <ThumbsUp className={cn("h-3.5 w-3.5", message.feedback === "up" && "fill-current")} />
                        </button>
                        <button
                          type="button"
                          onClick={() => void setMessageFeedback(message.id, "down")}
                          className={cn(
                            "inline-flex cursor-pointer items-center rounded-sm p-1 transition-colors",
                            message.feedback === "down"
                              ? "bg-[color:var(--danger)]/20 text-[color:var(--danger)] ring-1 ring-[color:var(--danger)]/40"
                              : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground",
                          )}
                          title="Not helpful"
                          aria-label="Not helpful"
                          aria-pressed={message.feedback === "down"}
                        >
                          <ThumbsDown className={cn("h-3.5 w-3.5", message.feedback === "down" && "fill-current")} />
                        </button>
                      </div>
                    )}
                    {showPostAnimationActions && message.feedback === "down" && (
                      <div className="mt-2" onClick={(event) => event.stopPropagation()}>
                        <Textarea
                          value={message.feedbackComment ?? ""}
                          onChange={(event) => setFeedbackComment(message.id, event.target.value)}
                          onBlur={(event) => {
                            const value = event.target.value.trim();
                            if (value) {
                              void setMessageFeedback(message.id, "down", value);
                            }
                          }}
                          placeholder="What was wrong? (optional)"
                          className="min-h-[52px] resize-none text-xs"
                          rows={2}
                        />
                      </div>
                    )}
                    {message.isServiceError && !isAnimating && message.retryQuestion && (
                      <div className="mt-2.5">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 gap-1.5 text-[10px]"
                          disabled={asking || !canAsk}
                          onClick={(event) => {
                            event.stopPropagation();
                            void retryAsk(message.retryQuestion!, message.id);
                          }}
                        >
                          <RefreshCw className="h-3 w-3" />
                          Retry
                        </Button>
                      </div>
                    )}
                    {isAgentReply && message.citations && message.citations.length > 0 && (
                      <div className="mt-2.5 border-t border-border/50 pt-2">
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Sources</div>
                        <div className="flex flex-wrap gap-1.5">
                          {message.citations.map((item, index) => (
                            <button
                              key={item.chunk_id ?? `${item.document_id}-${item.chunk_index ?? index}`}
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                setSelectedAgentMessageId(message.id);
                                openDocumentWithChunk(item.document_id, item.chunk_id, true);
                              }}
                              className="rounded-md border border-border/70 bg-secondary/50 px-2 py-1 text-[10px] text-foreground hover:bg-secondary"
                            >
                              {item.title}
                              {item.relevance_score > 0 && (
                                <span className="ml-1 text-muted-foreground">· {Math.round(item.relevance_score * 100)}%</span>
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {showCollapsibleDetails && (
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleMessageDetails(message.id);
                        }}
                        className="mt-2.5 inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
                      >
                        <ChevronDown className={cn("h-3 w-3 transition-transform", detailsOpen && "rotate-180")} />
                        {detailsOpen ? "Hide details" : "Details"}
                      </button>
                    )}
                    {showCollapsibleDetails && detailsOpen && (
                      <div className="mt-2 space-y-2.5">
                        {message.confidence_reasons && message.confidence_reasons.length > 0 && (
                          <div className="rounded-sm border border-border/60 bg-secondary/40 px-2.5 py-2">
                            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Why this confidence</div>
                            <ul className="space-y-0.5 text-[11px] leading-4 text-muted-foreground">
                              {message.confidence_reasons.map((reason) => (
                                <li key={reason}>• {reason}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {message.regenerationSummary && (
                          <div className="rounded-sm border border-[color:var(--brand)]/20 bg-[color:var(--brand)]/5 px-2.5 py-2">
                            <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--brand)]/70">What changed</div>
                            <p className="text-[11px] leading-4 text-muted-foreground">{message.regenerationSummary}</p>
                          </div>
                        )}
                        {message.retrieval_debug && (
                          <div className="rounded-sm border border-border/60 bg-secondary/30 px-2.5 py-2">
                            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Why these sources?</div>
                            <div className="space-y-1 text-[11px] leading-4 text-muted-foreground">
                              {message.retrieval_debug.retrieval_query && (
                                <p>Search query: {message.retrieval_debug.retrieval_query}</p>
                              )}
                              <p>
                                Scope: {message.retrieval_debug.project || "All projects"}
                                {message.retrieval_debug.department ? ` / ${message.retrieval_debug.department}` : ""}
                                {message.retrieval_debug.include_histories === false ? " / histories off" : ""}
                              </p>
                              <p>
                                Candidates: {message.retrieval_debug.eligible_doc_count ?? "n/a"} docs
                                {message.retrieval_debug.has_embeddings === false ? " / keyword fallback" : " / hybrid search"}
                              </p>
                              {message.retrieval_debug.sources && message.retrieval_debug.sources.length > 0 && (
                                <div className="mt-1 space-y-1">
                                  {message.retrieval_debug.sources.slice(0, 5).map((source) => (
                                    <div key={source.chunk_id} className="rounded-sm bg-card/70 px-2 py-1">
                                      <span className="font-medium text-foreground">{source.title}</span>
                                      <span className="ml-1">
                                        relevance {Math.round(source.relevance_score * 100)}%,
                                        vector {Math.round(source.vector_score * 100)}%,
                                        keyword {Math.round(source.keyword_score * 100)}%
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                        {message.structured_answer && (
                          <div className="space-y-2 rounded-sm border border-border/60 bg-secondary/30 p-2.5">
                            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Operational answer</div>
                            {message.structured_answer.policy && <StructuredField label="Policy" value={message.structured_answer.policy} />}
                            {message.structured_answer.steps && <StructuredField label="Steps" value={message.structured_answer.steps} />}
                            {message.structured_answer.owner && <StructuredField label="Owner" value={message.structured_answer.owner} />}
                            {message.structured_answer.evidence && <StructuredField label="Evidence" value={message.structured_answer.evidence} />}
                            {message.structured_answer.next_action && <StructuredField label="Next action" value={message.structured_answer.next_action} />}
                          </div>
                        )}
                        {message.next_step && (
                          <div className="rounded-sm border border-[color:var(--brand)]/20 bg-[color:var(--brand)]/5 px-2.5 py-2">
                            <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--brand)]/70">Recommended next step</div>
                            <p className="text-[11px] leading-4 text-foreground">{message.next_step}</p>
                          </div>
                        )}
                        {message.knowledge_gap && !message.isServiceError && (
                          <div className="rounded-sm border border-[color:var(--warning)]/30 bg-[color:var(--warning)]/8 p-2.5">
                            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[color:var(--warning)]">Missing knowledge</div>
                            <p className="text-[11px] leading-4 text-foreground">{message.knowledge_gap.message}</p>
                            <div className="mt-2 flex flex-wrap gap-2">
                              <Button type="button" size="sm" variant="outline" className="h-7 text-[10px]" onClick={() => prefillUploadFromGap(message.knowledge_gap!)}>
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
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Knowledge Agent</div>
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
              {!canAsk && (
                <p className="text-xs text-muted-foreground">Upload and approve documents first.</p>
              )}
              <div className="flex items-center gap-2">
              <Textarea
                placeholder={canAsk ? "Ask about an SOP, guide, or historical issue..." : "Upload and approve documents first"}
                value={askInput}
                disabled={asking || !canAsk}
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
                disabled={asking || !canAsk}
                className="h-10 shrink-0 gap-2 bg-[color:var(--brand)] px-4 text-xs text-[color:var(--brand-foreground)]"
              >
                <Send className="h-3.5 w-3.5" />
                {asking ? "Asking" : "Ask"}
              </Button>
              </div>
            </form>
          </Card>

        </div>

      </div>
      )}

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
                  <DocBadge label={selectedDoc.workflowState} />
                  <DocBadge label={selectedDoc.status} />
                </div>
              </DialogHeader>

              <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[1fr_18rem]">
                <div className="min-h-0 rounded-md bg-secondary/50 p-4">
                  <Tabs value={documentTab} onValueChange={setDocumentTab} className="flex h-full min-h-0 flex-col">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <TabsList className="h-8 bg-card/70">
                        <TabsTrigger value="preview" className="px-2.5 py-1 text-xs data-[state=active]:shadow-none">Preview</TabsTrigger>
                        <TabsTrigger value="metadata" className="px-2.5 py-1 text-xs data-[state=active]:shadow-none">Metadata</TabsTrigger>
                        <TabsTrigger value="chunks" className="px-2.5 py-1 text-xs data-[state=active]:shadow-none">Chunks</TabsTrigger>
                        <TabsTrigger value="versions" className="px-2.5 py-1 text-xs data-[state=active]:shadow-none">Versions</TabsTrigger>
                        <TabsTrigger value="evidence" className="px-2.5 py-1 text-xs data-[state=active]:shadow-none">Evidence</TabsTrigger>
                      </TabsList>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {selectedDoc.indexing && <DocBadge label={selectedDoc.processingLabel} tone="info" />}
                        {selectedDoc.processingStatus === "ready" && <DocBadge label="Ready" tone="success" />}
                        {selectedDoc.processingStatus === "failed" && <DocBadge label="Failed" tone="danger" />}
                      </div>
                    </div>

                    <TabsContent value="preview" className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2">
                      <div className="space-y-3 text-sm leading-6">
                        {selectedDoc.preview.map((paragraph) => (
                          <FormattedPreview key={paragraph} text={paragraph} />
                        ))}
                      </div>
                      {!isRetrievalReady(selectedDoc) && (
                        <div className="mt-4 rounded-md bg-[color:var(--warning)]/10 p-3 text-xs leading-5 text-muted-foreground">
                          This document is not currently eligible for Ask Knowledge Agent retrieval. It must be Approved and Ready.
                        </div>
                      )}
                    </TabsContent>

                    <TabsContent value="metadata" className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2">
                      <div className="grid gap-2 text-xs sm:grid-cols-2">
                        <InfoTile label="Source type" value={selectedDoc.sourceType} />
                        <InfoTile label="Visibility" value={selectedDoc.visibility} />
                        <InfoTile label="Workflow" value={selectedDoc.workflowState} />
                        <InfoTile label="Status" value={selectedDoc.status} />
                        <InfoTile label="Version" value={selectedDoc.version} />
                        <InfoTile label="Owner/Approver" value={selectedDoc.owner} />
                        <InfoTile label="Effective date" value={selectedDoc.effectiveDate || "Not set"} />
                        <InfoTile label="Approved by" value={selectedDoc.approvedByName || "Not approved"} />
                        <InfoTile label="Chunks" value={String(selectedDoc.chunkCount)} />
                        <InfoTile label="Citations" value={String(selectedDoc.citationCount)} />
                      </div>
                      {selectedDoc.qualityScore && (
                        <div className="mt-4 rounded-md border border-border/70 bg-card/60 p-3">
                          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Document quality</div>
                          <QualityScoreBadge score={selectedDoc.qualityScore} detailed />
                        </div>
                      )}
                    </TabsContent>

                    <TabsContent value="chunks" className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2">
                      {loadingDocDetail && selectedDoc.chunks.length === 0 ? (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          Loading chunks...
                        </div>
                      ) : (
                      <div className="space-y-2 text-xs">
                        {selectedDoc.chunks.length === 0 && selectedDoc.preview.map((paragraph, index) => (
                          <div key={`${selectedDoc.id}-chunk-${index}`} className="rounded-md border border-border/70 bg-card/60 p-3">
                            <div className="mb-1 font-medium text-muted-foreground">Chunk {index + 1}</div>
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
                                <span className="rounded bg-[color:var(--brand)]/10 px-1.5 py-0.5 text-[10px] text-[color:var(--brand)]">Cited</span>
                              )}
                            </div>
                            <FormattedPreview text={chunk.chunkText} compact />
                          </div>
                        ))}
                      </div>
                      )}
                    </TabsContent>

                    <TabsContent value="versions" className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2">
                      <div className="space-y-3 text-xs">
                        {versions.map((version) => (
                          <div key={version.id} className="rounded-md border border-border/70 bg-card/60 p-3">
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
                              {version.approved_by_name ? ` · Approved by ${version.approved_by_name}` : ""}
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
                                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Left version" /></SelectTrigger>
                                <SelectContent>
                                  {versions.map((v) => <SelectItem key={v.id} value={v.id}>{v.version}</SelectItem>)}
                                </SelectContent>
                              </Select>
                              <Select value={compareRightId} onValueChange={setCompareRightId}>
                                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Right version" /></SelectTrigger>
                                <SelectContent>
                                  {versions.map((v) => <SelectItem key={v.id} value={v.id}>{v.version}</SelectItem>)}
                                </SelectContent>
                              </Select>
                            </div>
                            <Button type="button" size="sm" className="mt-2 h-8 text-xs" onClick={() => void runVersionCompare()}>
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
                                      {versionCompare.added_sections.map((line) => <li key={line}>{line}</li>)}
                                    </ul>
                                  </div>
                                )}
                                {(versionCompare.left_approved_by || versionCompare.right_approved_by) && (
                                  <div className="text-muted-foreground">
                                    Approved by: {versionCompare.right_approved_by || versionCompare.left_approved_by || "Unknown"}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </TabsContent>

                    <TabsContent value="evidence" className="mt-4 min-h-0 flex-1 overflow-y-auto pr-2">
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
                      <Select value={selectedDoc.folderId} onValueChange={(value) => void updateDocument(selectedDoc.id, { folderId: value })}>
                        <SelectTrigger className="h-8 border-transparent bg-transparent px-2 text-xs shadow-none hover:bg-secondary/70">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {libraryFolders.map((folder) => (
                            <SelectItem key={folder.id} value={folder.id}>{folder.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid grid-cols-[4.5rem_1fr] items-center gap-2 rounded-md border border-border/70 bg-card/60 px-2 py-1 text-xs">
                      <span className="text-muted-foreground">Status</span>
                      <Select value={selectedDoc.status} onValueChange={(value) => void updateDocument(selectedDoc.id, { status: value as DocumentStatus })}>
                        <SelectTrigger className="h-8 border-transparent bg-transparent px-2 text-xs shadow-none hover:bg-secondary/70">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {statuses.map((status) => (
                            <SelectItem key={status} value={status}>{status}</SelectItem>
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

      <Dialog open={isUploadOpen} onOpenChange={(open) => {
        setIsUploadOpen(open);
        if (!open) resetUpload();
      }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Upload Document</DialogTitle>
            <DialogDescription>
              Add a governed source. The agent can retrieve it only after it is approved and indexed.
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
              <div className="font-medium text-foreground">{selectedFile ? selectedFile.name : "Drop file here"}</div>
              <div className="mt-1 text-muted-foreground">or click to choose PDF, DOCX, TXT, MD, or CSV</div>
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
                <Input value={form.title} onChange={(event) => setField("title", event.target.value)} className="h-9 text-xs shadow-none" />
              </Field>
              <Field label="Folder">
                <Select value={form.folderId} onValueChange={(value) => setField("folderId", value)}>
                  <SelectTrigger className="h-9 text-xs shadow-none"><SelectValue placeholder="Select folder" /></SelectTrigger>
                  <SelectContent>
                    {libraryFolders.map((folder) => (
                      <SelectItem key={folder.id} value={folder.id}>{folder.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Source type">
                <Select value={form.sourceType} onValueChange={(value) => setField("sourceType", value as SourceType)}>
                  <SelectTrigger className="h-9 text-xs shadow-none"><SelectValue /></SelectTrigger>
                  <SelectContent>{sourceTypes.map((type) => <SelectItem key={type} value={type}>{type}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Version">
                <Input value={form.version} onChange={(event) => setField("version", event.target.value)} className="h-9 text-xs shadow-none" />
              </Field>
              <Field label="Visibility">
                <Select value={form.visibility} onValueChange={(value) => setField("visibility", value as Visibility)}>
                  <SelectTrigger className="h-9 text-xs shadow-none"><SelectValue /></SelectTrigger>
                  <SelectContent>{visibilities.map((visibility) => <SelectItem key={visibility} value={visibility}>{visibility}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Status">
                <Select value={form.status} onValueChange={(value) => setField("status", value as DocumentStatus)}>
                  <SelectTrigger className="h-9 text-xs shadow-none"><SelectValue /></SelectTrigger>
                  <SelectContent>{statuses.map((status) => <SelectItem key={status} value={status}>{status}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Effective date">
                <Input type="date" value={form.effectiveDate} onChange={(event) => setField("effectiveDate", event.target.value)} className="h-9 text-xs shadow-none" />
              </Field>
              <Field className="col-span-2" label="Owner/Approver">
                <Input value={form.owner} onChange={(event) => setField("owner", event.target.value)} className="h-9 text-xs shadow-none" />
              </Field>
            </div>
          </div>

          {uploadState !== "idle" && (
            <div className="rounded-md bg-secondary/50 p-3 text-xs">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-medium">
                  {uploadState === "uploading" && "Uploading document..."}
                  {uploadState === "success" && "Upload complete. Indexing..."}
                  {uploadState === "error" && "Upload failed"}
                </span>
                {uploadState === "success" ? <CheckCircle2 className="h-4 w-4 text-[color:var(--success)]" /> : null}
                {uploadState === "uploading" ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
              </div>
              {uploadState !== "error" && <Progress value={uploadProgress} />}
              {uploadState === "error" && <p className="text-[color:var(--danger)]">{uploadError}</p>}
              {uploadWarning && (
                <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-800 dark:text-amber-200">
                  {uploadWarning}
                </p>
              )}
              {uploadState === "success" && <p className="mt-2 text-muted-foreground">The document is visible in the selected folder while chunks and embeddings are prepared.</p>}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setIsUploadOpen(false)}>Cancel</Button>
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
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</div>
      <p className="mt-0.5 text-[11px] leading-4 text-foreground whitespace-pre-wrap">{value}</p>
    </div>
  );
}

function QualityScoreBadge({
  score,
  detailed = false,
}: {
  score: { score: number; max_score: number; criteria: Array<{ key: string; label: string; passed: boolean }> };
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
                item.passed ? "bg-[color:var(--success)]/10 text-[color:var(--success)]" : "bg-secondary text-muted-foreground",
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

function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
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
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
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
            <h4 key={`${line.text}-${index}`} className="pt-1 text-sm font-semibold text-foreground">
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

function formatPreviewLines(text: string): Array<{ kind: "heading" | "bullet" | "paragraph"; text: string }> {
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
      if (/^\d+[\.)]\s+/.test(line)) return { kind: "bullet", text: line };
      if (/^(Purpose|Scope|Procedure|Responsibilities|Requirements|Project Summary|Challenges Encountered|Actions Taken|Results|Recommendations|Best Practices|Lessons Learned|Quality Guidance)$/i.test(line)) {
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
  if (label === "Approved" || label === "Draft" || label === "Archived") return <StatusPill status={label} />;
  const classes =
    tone === "success"
      ? "border-[color:var(--success)]/30 bg-[color:var(--success)]/15 text-[color:var(--success)]"
      : tone === "danger"
        ? "border-[color:var(--danger)]/30 bg-[color:var(--danger)]/10 text-[color:var(--danger)]"
      : "border-[color:var(--info)]/30 bg-[color:var(--info)]/15 text-[color:var(--info)]";
  return <span className={cn("inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-medium", classes)}>{label}</span>;
}

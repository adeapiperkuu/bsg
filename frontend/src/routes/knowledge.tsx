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
import {
  askKnowledgeAgent,
  compareKnowledgeDocumentVersions,
  createKnowledgeFolder,
  deleteKnowledgeDocument,
  downloadKnowledgeDocumentFile,
  getKnowledgeDocument,
  listKnowledgeDocumentVersions,
  listKnowledgeDocuments,
  listKnowledgeFolders,
  reindexKnowledgeDocument,
  updateKnowledgeDocument,
  uploadKnowledgeDocument,
} from "@/lib/api";
import { KnowledgeRetrievalPanel } from "@/components/knowledge/KnowledgeRetrievalPanel";
import { TypewriterText } from "@/components/knowledge/TypewriterText";
import { TypingIndicator } from "@/components/knowledge/TypingIndicator";
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
  KnowledgeCitationApi,
  KnowledgeDocumentVersionApi,
  KnowledgeFolderKind,
  KnowledgeGapApi,
  KnowledgeRetrievalSettingsApi,
  KnowledgeStructuredAnswerApi,
  KnowledgeVersionCompareApi,
} from "@/types/knowledge";
import {
  Archive,
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
  Library,
  Loader2,
  Plus,
  Send,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";

export const Route = createFileRoute("/knowledge")({ component: KnowledgePage });

type UploadState = "idle" | "uploading" | "success" | "error";
type SortMode = "recent" | "title" | "approved" | "indexed";
type HealthFilter = "all" | "ready" | "needs_approval" | "indexing" | "archived";
type ChatMessage = {
  role: "user" | "agent";
  text: string;
  next_step?: string;
  confidence_score?: number;
  confidence_reasons?: string[];
  structured_answer?: KnowledgeStructuredAnswerApi | null;
  knowledge_gap?: KnowledgeGapApi | null;
  citations?: KnowledgeCitationApi[];
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
const suggestedQuestions = [
  "When should a quality escalation be triggered?",
  "What actions improved quality in Project Alpha?",
  "What are the onboarding steps before production launch?",
];

const initialDocuments: KnowledgeDocument[] = [];

function KnowledgePage() {
  const user = useAuthStore((s) => s.user);
  const canManageRetrieval = user?.role === "bsg_leadership" || user?.role === "super_admin";
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
  const [animatingMessageIndex, setAnimatingMessageIndex] = useState<number | null>(null);
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
  const selectedDoc = documents.find((item) => item.id === docId) ?? null;
  const selectedDocId = selectedDoc?.id ?? null;
  const approvedIndexedDocs = documents.filter(isRetrievalReady);
  const draftCount = documents.filter((item) => item.status === "Draft").length;
  const indexingCount = documents.filter((item) => item.indexing).length;
  const archivedCount = documents.filter((item) => item.status === "Archived").length;
  const healthFilters = [
    { id: "all" as const, label: "All", count: documents.length },
    { id: "ready" as const, label: "Ready", count: approvedIndexedDocs.length },
    { id: "needs_approval" as const, label: "Needs approval", count: draftCount },
    { id: "indexing" as const, label: "Indexing", count: indexingCount },
    { id: "archived" as const, label: "Archived", count: archivedCount },
  ];

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

  const scrollChatToEnd = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  useEffect(() => {
    scrollChatToEnd();
  }, [asking, messages.length, animatingMessageIndex]);

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

    const file = selectedFile;
    if (!file) return;

    setUploadState("uploading");
    setUploadError("");
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
    setDocId((current) =>
      current === document.id
        ? (previous.find((item) => item.id !== document.id)?.id ?? null)
        : current,
    );
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

  const submitAsk = async () => {
    const question = askInput.trim();
    if (!question || asking || animatingMessageIndex !== null) return;
    setMessages((current) => [...current, { role: "user", text: question }]);
    setAskInput("");
    setAsking(true);
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
      const fallback = "I could not find this information in the uploaded knowledge base.";
      setMessages((current) => {
        const next = [
          ...current,
          {
            role: "agent" as const,
            text: fallback,
            confidence_score: 0,
            confidence_reasons: ["The knowledge service could not complete the request."],
            knowledge_gap: {
              message: fallback,
              suggested_title: question.slice(0, 80),
              suggested_source_type: "sop",
              suggested_folder_kind: "sops",
            },
          },
        ];
        setAnimatingMessageIndex(next.length - 1);
        return next;
      });
      setActiveSources([]);
      setLastConfidence(0);
    } finally {
      setAsking(false);
    }
  };

  const handleAsk = (event: FormEvent) => {
    event.preventDefault();
    void submitAsk();
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

  const prefillUploadFromGap = (gap: KnowledgeGapApi) => {
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
              })}
              {asking && (
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

            <form className="flex shrink-0 gap-2 p-5 pt-4" onSubmit={handleAsk}>
              <input
                placeholder="Ask about an SOP, guide, or historical issue..."
                value={askInput}
                disabled={asking || animatingMessageIndex !== null}
                onChange={(event) => setAskInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submitAsk();
                  }
                }}
                className="min-h-10 flex-1 rounded-md border border-border bg-card px-3 py-2 text-sm outline-none focus:border-[color:var(--brand)]"
              />
              <Button
                type="submit"
                disabled={asking || animatingMessageIndex !== null}
                className="h-10 gap-2 bg-[color:var(--brand)] px-4 text-xs text-[color:var(--brand-foreground)]"
              >
                <Send className="h-3.5 w-3.5" />
                {asking ? "Asking" : animatingMessageIndex !== null ? "Replying" : "Ask"}
              </Button>
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
                  <DocBadge label={selectedDoc.workflowState} />
                  <DocBadge label={selectedDoc.status} />
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
                  {uploadState === "success" && "Upload complete. Indexing..."}
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

import { GitCompare, Loader2 } from "lucide-react";

import { DocBadge, FormattedPreview, InfoTile, QualityScoreBadge } from "@/components/knowledge/knowledge-ui";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { DocumentDetailTab } from "@/hooks/useDocumentTabLoader";
import { isRetrievalReady, type KnowledgeDocument } from "@/lib/knowledge-mappers";
import type { KnowledgeDocumentVersionApi, KnowledgeVersionCompareApi } from "@/types/knowledge";
import { cn } from "@/lib/utils";

export type KnowledgeDocumentTabPanelsProps = {
  activeTab: DocumentDetailTab;
  selectedDoc: KnowledgeDocument;
  activeChunkId: string | null;
  loadingDetail: boolean;
  loadingVersions: boolean;
  versions: KnowledgeDocumentVersionApi[];
  versionCompare: KnowledgeVersionCompareApi | null;
  compareLeftId: string;
  compareRightId: string;
  onCompareLeftChange: (value: string) => void;
  onCompareRightChange: (value: string) => void;
  onRunVersionCompare: () => void;
};

function InlineLoadingBadge({ label }: { label: string }) {
  return (
    <div className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-card/70 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
      <Loader2 className="h-3 w-3 animate-spin" />
      {label}
    </div>
  );
}

function ParagraphSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-4 w-11/12" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-4/5" />
    </div>
  );
}

function DetailSkeletonGrid() {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="rounded-md border border-border/70 bg-card/60 p-3">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-2 h-4 w-28" />
        </div>
      ))}
    </div>
  );
}

export function KnowledgeDocumentPreviewTab({
  selectedDoc,
  loadingDetail,
}: Pick<KnowledgeDocumentTabPanelsProps, "selectedDoc" | "loadingDetail">) {
  if (loadingDetail && selectedDoc.preview.length === 0) {
    return (
      <div>
        <InlineLoadingBadge label="Loading preview" />
        <ParagraphSkeleton />
      </div>
    );
  }

  return (
    <div className="space-y-3 text-sm leading-6">
      {loadingDetail && <InlineLoadingBadge label="Refreshing preview" />}
      {selectedDoc.preview.map((paragraph) => (
        <FormattedPreview key={paragraph} text={paragraph} />
      ))}
      {!isRetrievalReady(selectedDoc) && (
        <div className="mt-4 rounded-md bg-[color:var(--warning)]/10 p-3 text-xs leading-5 text-muted-foreground">
          This document is not currently eligible for Ask Knowledge Agent retrieval. It must be Approved and Ready.
        </div>
      )}
    </div>
  );
}

export function KnowledgeDocumentMetadataTab({
  selectedDoc,
  loadingDetail,
}: Pick<KnowledgeDocumentTabPanelsProps, "selectedDoc" | "loadingDetail">) {
  if (loadingDetail && selectedDoc.chunkCount === 0 && !selectedDoc.qualityScore) {
    return (
      <div>
        <InlineLoadingBadge label="Loading embedding details" />
        <DetailSkeletonGrid />
      </div>
    );
  }

  return (
    <>
      {loadingDetail && <InlineLoadingBadge label="Refreshing metadata" />}
      <div className="grid gap-2 text-xs sm:grid-cols-2">
        <InfoTile label="Source type" value={selectedDoc.sourceType} />
        <InfoTile label="Visibility" value={selectedDoc.visibility} />
        <InfoTile label="Workflow" value={selectedDoc.workflowState} />
        <InfoTile label="Status" value={selectedDoc.status} />
        <InfoTile label="Version" value={selectedDoc.version} />
        <InfoTile label="Owner/Approver" value={selectedDoc.owner} />
        <InfoTile label="Effective date" value={selectedDoc.effectiveDate || "Not set"} />
        <InfoTile label="Approved by" value={selectedDoc.approvedByName || "Not approved"} />
        <InfoTile label="Processing" value={selectedDoc.processingLabel} />
        <InfoTile label="Indexing" value={selectedDoc.indexed ? "Indexed" : selectedDoc.indexing ? "In progress" : "Not indexed"} />
        <InfoTile label="Chunks" value={String(selectedDoc.chunkCount)} />
        <InfoTile label="Citations" value={String(selectedDoc.citationCount)} />
      </div>
      {selectedDoc.qualityScore && (
        <div className="mt-4 rounded-md border border-border/70 bg-card/60 p-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Document quality</div>
          <QualityScoreBadge score={selectedDoc.qualityScore} detailed />
        </div>
      )}
    </>
  );
}

export function KnowledgeDocumentChunksTab({
  selectedDoc,
  activeChunkId,
  loadingDetail,
}: Pick<KnowledgeDocumentTabPanelsProps, "selectedDoc" | "activeChunkId" | "loadingDetail">) {
  if (loadingDetail && selectedDoc.chunks.length === 0) {
    return (
      <div>
        <InlineLoadingBadge label="Loading chunks" />
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="rounded-md border border-border/70 bg-card/60 p-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-4 w-full" />
              <Skeleton className="mt-2 h-4 w-5/6" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2 text-xs">
      {loadingDetail && <InlineLoadingBadge label="Refreshing chunks" />}
      {selectedDoc.chunks.length === 0 &&
        selectedDoc.preview.map((paragraph, index) => (
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
            activeChunkId === chunk.id ? "border-[color:var(--brand)] ring-2 ring-[color:var(--brand)]/20" : "border-border/70",
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
  );
}

export function KnowledgeDocumentVersionsTab({
  versions,
  loadingVersions,
  versionCompare,
  compareLeftId,
  compareRightId,
  onCompareLeftChange,
  onCompareRightChange,
  onRunVersionCompare,
}: Pick<
  KnowledgeDocumentTabPanelsProps,
  | "versions"
  | "loadingVersions"
  | "versionCompare"
  | "compareLeftId"
  | "compareRightId"
  | "onCompareLeftChange"
  | "onCompareRightChange"
  | "onRunVersionCompare"
>) {
  if (loadingVersions && versions.length === 0) {
    return (
      <div>
        <InlineLoadingBadge label="Loading re-index history" />
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="rounded-md border border-border/70 bg-card/60 p-3">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="mt-2 h-3 w-48" />
              <Skeleton className="mt-2 h-3 w-32" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 text-xs">
      {loadingVersions && <InlineLoadingBadge label="Refreshing history" />}
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
            <Select value={compareLeftId} onValueChange={onCompareLeftChange}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Left version" />
              </SelectTrigger>
              <SelectContent>
                {versions.map((version) => (
                  <SelectItem key={version.id} value={version.id}>
                    {version.version}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={compareRightId} onValueChange={onCompareRightChange}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Right version" />
              </SelectTrigger>
              <SelectContent>
                {versions.map((version) => (
                  <SelectItem key={version.id} value={version.id}>
                    {version.version}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button type="button" size="sm" className="mt-2 h-8 text-xs" onClick={onRunVersionCompare}>
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
  );
}

export function KnowledgeDocumentEvidenceTab({
  selectedDoc,
  loadingDetail,
}: Pick<KnowledgeDocumentTabPanelsProps, "selectedDoc" | "loadingDetail">) {
  if (loadingDetail && selectedDoc.citationCount === 0 && !isRetrievalReady(selectedDoc)) {
    return (
      <div>
        <InlineLoadingBadge label="Loading citation details" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  return (
    <>
      {loadingDetail && <InlineLoadingBadge label="Refreshing citations" />}
      <div className="rounded-md border border-border/70 bg-card/60 p-4 text-xs leading-5 text-muted-foreground">
        {isRetrievalReady(selectedDoc)
          ? `This document has been cited ${selectedDoc.citationCount} time(s) and is eligible for Ask Knowledge Agent answers.`
          : "This document is visible for review, but it will not be used as answer evidence until it is approved and ready."}
      </div>
    </>
  );
}

export function KnowledgeDocumentTabPanels(props: KnowledgeDocumentTabPanelsProps) {
  const { activeTab } = props;

  return (
    <div
      key={activeTab}
      className="mt-4 min-h-0 flex-1 animate-in fade-in-0 overflow-y-auto pr-2 duration-200"
    >
      {activeTab === "preview" && <KnowledgeDocumentPreviewTab selectedDoc={props.selectedDoc} loadingDetail={props.loadingDetail} />}
      {activeTab === "metadata" && <KnowledgeDocumentMetadataTab selectedDoc={props.selectedDoc} loadingDetail={props.loadingDetail} />}
      {activeTab === "chunks" && (
        <KnowledgeDocumentChunksTab
          selectedDoc={props.selectedDoc}
          activeChunkId={props.activeChunkId}
          loadingDetail={props.loadingDetail}
        />
      )}
      {activeTab === "versions" && (
        <KnowledgeDocumentVersionsTab
          versions={props.versions}
          loadingVersions={props.loadingVersions}
          versionCompare={props.versionCompare}
          compareLeftId={props.compareLeftId}
          compareRightId={props.compareRightId}
          onCompareLeftChange={props.onCompareLeftChange}
          onCompareRightChange={props.onCompareRightChange}
          onRunVersionCompare={props.onRunVersionCompare}
        />
      )}
      {activeTab === "evidence" && <KnowledgeDocumentEvidenceTab selectedDoc={props.selectedDoc} loadingDetail={props.loadingDetail} />}
    </div>
  );
}

import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import type { ReportPreview } from "@/types/reports";

export function ReportPreviewPanel({
  preview,
  loading,
  error,
}: {
  preview?: ReportPreview | null;
  loading?: boolean;
  error?: unknown;
}) {
  return (
    <Card>
      <SectionHeader
        title={preview?.title ?? "Report Preview"}
        sub={preview ? `${preview.sections.length} sections` : undefined}
        right={
          preview ? (
            <StatusPill
              status={preview.requires_approval ? "Warning" : "On Track"}
            />
          ) : undefined
        }
      />
      {loading ? (
        <div className="py-8 text-center text-sm text-muted-foreground" role="status">
          Loading preview…
        </div>
      ) : error ? (
        <div className="py-8 text-center text-sm text-[color:var(--danger)]" role="alert">
          Unable to load report preview.
        </div>
      ) : !preview ? (
        <div className="py-8 text-center text-sm text-muted-foreground" role="status">
          Select a report to preview.
        </div>
      ) : (
        <div className="space-y-4" aria-live="polite">
          {preview.has_ai_sections ? (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs">
              AI-authored sections require human approval before distribution.
            </div>
          ) : null}
          <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-lg bg-[color:var(--panel-2)] p-3 text-xs">
            {preview.body_markdown || "No markdown body."}
          </pre>
          {preview.limitations.length > 0 ? (
            <div className="text-xs text-muted-foreground">
              Limitations: {preview.limitations.join("; ")}
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}

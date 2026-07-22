import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import type { ReportTemplate } from "@/types/reports";

export function ReportTemplateList({
  templates,
  selectedId,
  onSelect,
  loading,
}: {
  templates: ReportTemplate[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  loading?: boolean;
}) {
  return (
    <Card>
      <SectionHeader title="Templates" sub={`${templates.length} active`} />
      {loading ? (
        <div className="py-6 text-center text-sm text-muted-foreground">Loading templates…</div>
      ) : (
        <ul className="space-y-2">
          {templates.map((template) => (
            <li key={template.id}>
              <button
                type="button"
                className={`flex w-full items-start justify-between rounded-lg border px-3 py-2 text-left text-sm ${
                  selectedId === template.id
                    ? "border-[color:var(--accent)] bg-[color:var(--panel-2)]"
                    : "border-[color:var(--border)]"
                }`}
                onClick={() => onSelect?.(template.id)}
              >
                <span>
                  <span className="font-medium">{template.name}</span>
                  <span className="mt-0.5 block text-[11px] text-muted-foreground">
                    {template.template_key}@{template.version} · {template.domain}
                  </span>
                </span>
                <StatusPill status={template.requires_approval ? "Warning" : "On Track"} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

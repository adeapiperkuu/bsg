import { Card, SectionHeader } from "@/components/bsg/widgets";
import type { ReportSectionConfig } from "@/types/reports";

export function ReportSectionEditor({
  sections,
  onChange,
  readOnly,
}: {
  sections: ReportSectionConfig[];
  onChange?: (next: ReportSectionConfig[]) => void;
  readOnly?: boolean;
}) {
  return (
    <Card>
      <SectionHeader title="Sections" sub="Ordered composition for this template" />
      <ol className="space-y-2" aria-label="Report sections">
        {sections.map((section, index) => (
          <li
            key={`${section.key}-${index}`}
            className="rounded-lg border border-[color:var(--border)] px-3 py-2 text-sm"
          >
            <div className="font-medium">
              {index + 1}. {section.key}
            </div>
            {!readOnly ? (
              <textarea
                className="mt-2 w-full rounded-md border border-[color:var(--border)] bg-transparent p-2 font-mono text-[11px]"
                rows={3}
                value={JSON.stringify(section.options ?? {}, null, 2)}
                onChange={(e) => {
                  try {
                    const options = JSON.parse(e.target.value || "{}") as Record<string, unknown>;
                    const next = sections.map((item, i) =>
                      i === index ? { ...item, options } : item,
                    );
                    onChange?.(next);
                  } catch {
                    // keep typing until JSON is valid
                  }
                }}
                aria-label={`Options for ${section.key}`}
              />
            ) : (
              <pre className="mt-1 overflow-auto text-[11px] text-muted-foreground">
                {JSON.stringify(section.options ?? {}, null, 2)}
              </pre>
            )}
          </li>
        ))}
      </ol>
    </Card>
  );
}

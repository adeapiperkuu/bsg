import type { AgentQueryEvidenceLinkRead } from "@/types/workforce";

export const DEFAULT_EVIDENCE_PREVIEW_COUNT = 4;

const SOURCE_TABLE_LABELS: Record<string, string> = {
  utilization_snapshots: "Utilization snapshot",
  teams: "Team",
  projects: "Project",
  project_skill_requirements: "Skill requirement",
  training_programs: "Training program",
  capability_gaps: "Capability gap",
  risk_alerts: "Risk alert",
  mitigation_recommendations: "Recommendation",
  annotators: "Annotator",
  skills: "Skill",
  employee_certifications: "Certification",
  training_records: "Training record",
};

export type DisplayEvidenceItem = {
  id: string;
  sourceLabel: string;
  description: string;
  rowIdShort: string | null;
};

export function friendlySourceLabel(sourceTable: string): string {
  const mapped = SOURCE_TABLE_LABELS[sourceTable];
  if (mapped) return mapped;

  return sourceTable
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function normalizeDescription(
  description: string,
  sourceTable: string,
  sourceLabel: string,
): string {
  const trimmed = description.trim();
  if (!trimmed) return "";

  const lower = trimmed.toLowerCase();
  if (lower === sourceTable.toLowerCase() || lower === sourceLabel.toLowerCase()) {
    return "";
  }

  if (lower.startsWith(`${sourceTable.toLowerCase()} `)) {
    return trimmed.slice(sourceTable.length).trim();
  }

  if (lower.startsWith(`${sourceLabel.toLowerCase()} `)) {
    return trimmed.slice(sourceLabel.length).trim();
  }

  return trimmed;
}

export function normalizeEvidenceLinks(links: AgentQueryEvidenceLinkRead[]): DisplayEvidenceItem[] {
  const seen = new Set<string>();
  const items: DisplayEvidenceItem[] = [];

  for (const link of links) {
    const sourceLabel = friendlySourceLabel(link.source_table);
    const description = normalizeDescription(link.description, link.source_table, sourceLabel);
    const dedupeKey = `${link.source_table}::${description || link.source_row_id}`;

    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    items.push({
      id: link.id ?? dedupeKey,
      sourceLabel,
      description,
      rowIdShort: link.source_row_id ? link.source_row_id.slice(0, 8) : null,
    });
  }

  return items;
}

export function confidenceLabel(confidence?: string | null): string | null {
  if (!confidence) return null;
  return confidence.charAt(0).toUpperCase() + confidence.slice(1);
}

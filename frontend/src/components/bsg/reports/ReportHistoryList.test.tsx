import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportHistoryList } from "@/components/bsg/reports/ReportHistoryList";
import { ReportTemplateList } from "@/components/bsg/reports/ReportTemplateList";
import type { ReportInstanceListItem, ReportTemplate } from "@/types/reports";

const template: ReportTemplate = {
  id: "t1",
  org_id: null,
  template_key: "quality.weekly_quality",
  name: "Quality Weekly Report",
  description: null,
  audience: "delivery_manager",
  domain: "quality",
  version: "1.0.0",
  status: "active",
  section_config: [{ key: "kpi_summary" }],
  export_formats: ["pdf", "json"],
  requires_approval: true,
  allowed_roles: ["delivery_manager"],
  is_client_visible: false,
  created_by: null,
  created_at: "2026-07-21T00:00:00Z",
  updated_at: "2026-07-21T00:00:00Z",
};

const report: ReportInstanceListItem = {
  id: "r1",
  org_id: "o1",
  project_id: "p1",
  template_key: "quality.weekly_quality",
  template_version: "1.0.0",
  audience: "delivery_manager",
  domain: "quality",
  status: "draft",
  title: "Quality Weekly",
  period_start: null,
  period_end: null,
  has_ai_sections: false,
  evidence_fingerprint: null,
  created_at: "2026-07-21T00:00:00Z",
  updated_at: "2026-07-21T00:00:00Z",
};

describe("shared report list components", () => {
  it("renders template builder list entries", () => {
    render(<ReportTemplateList templates={[template]} selectedId="t1" />);
    expect(screen.getByText("Quality Weekly Report")).toBeInTheDocument();
    expect(screen.getByText(/quality\.weekly_quality@1\.0\.0/)).toBeInTheDocument();
  });

  it("renders history empty and populated states", () => {
    const { rerender } = render(<ReportHistoryList reports={[]} />);
    expect(screen.getByText("No platform reports yet.")).toBeInTheDocument();
    rerender(<ReportHistoryList reports={[report]} selectedId="r1" />);
    expect(screen.getByText("Quality Weekly")).toBeInTheDocument();
  });
});

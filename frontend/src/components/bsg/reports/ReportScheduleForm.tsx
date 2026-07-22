import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import type { ReportScheduleCreate } from "@/types/reports";

export function ReportScheduleForm({
  templateId,
  onSubmit,
  busy,
}: {
  templateId?: string;
  onSubmit: (payload: ReportScheduleCreate) => Promise<void> | void;
  busy?: boolean;
}) {
  const [interval, setInterval] = useState<"daily" | "weekly" | "monthly" | "quarterly">(
    "weekly",
  );
  const [audience, setAudience] = useState("delivery_manager");
  return (
    <Card>
      <SectionHeader
        title="Schedule Report"
        sub="Schedules create drafts only — never approve or distribute."
      />
      <div className="grid gap-2 md:grid-cols-3">
        <label className="text-xs">
          Interval
          <select
            className="mt-1 w-full rounded-md border border-[color:var(--border)] bg-transparent px-2 py-1"
            value={interval}
            onChange={(e) => setInterval(e.target.value as typeof interval)}
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="quarterly">Quarterly</option>
          </select>
        </label>
        <label className="text-xs">
          Audience
          <input
            className="mt-1 w-full rounded-md border border-[color:var(--border)] bg-transparent px-2 py-1"
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
          />
        </label>
        <div className="flex items-end">
          <Button
            disabled={busy || !templateId}
            onClick={() =>
              void onSubmit({
                template_id: templateId!,
                interval,
                audience,
                create_as_status: "draft",
                is_enabled: true,
              })
            }
          >
            Create schedule
          </Button>
        </div>
      </div>
    </Card>
  );
}

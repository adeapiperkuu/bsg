import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import {
  downloadReportExport,
  listReportExports,
  requestReportExport,
} from "@/lib/api/reports";
import { queryKeys } from "@/lib/queries/keys";
import type { ReportFormat } from "@/types/reports";

const FORMATS: ReportFormat[] = ["pdf", "docx", "json", "csv"];

export function ReportExportButtons({ reportId }: { reportId: string | null | undefined }) {
  const queryClient = useQueryClient();
  const exportMutation = useMutation({
    mutationFn: async (format: ReportFormat) => {
      if (!reportId) throw new Error("Missing report");
      const created = await requestReportExport(reportId, format);
      const blob = await downloadReportExport(reportId, created.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = created.file_name;
      anchor.click();
      URL.revokeObjectURL(url);
      return created;
    },
    onSuccess: async () => {
      if (!reportId) return;
      await queryClient.invalidateQueries({ queryKey: queryKeys.reportExports(reportId) });
      toast.success("Export ready");
    },
    onError: () => toast.error("Export failed"),
  });

  return (
    <Card>
      <SectionHeader title="Platform Exports" sub="PDF · DOCX · JSON · CSV" />
      <div className="flex flex-wrap gap-2">
        {FORMATS.map((format) => (
          <Button
            key={format}
            variant="outline"
            size="sm"
            disabled={!reportId || exportMutation.isPending}
            onClick={() => exportMutation.mutate(format)}
          >
            {format.toUpperCase()}
          </Button>
        ))}
      </div>
      <button
        type="button"
        className="mt-2 text-[11px] text-muted-foreground underline"
        disabled={!reportId}
        onClick={() => {
          if (!reportId) return;
          void listReportExports(reportId);
        }}
      >
        Refresh export list
      </button>
    </Card>
  );
}

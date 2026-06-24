import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getKnowledgeRetrievalSettings, updateKnowledgeRetrievalSettings } from "@/lib/api";
import type { KnowledgeRetrievalSettingsApi } from "@/types/knowledge";
import { Settings2 } from "lucide-react";

type Props = {
  canManage: boolean;
  onChange?: (settings: KnowledgeRetrievalSettingsApi) => void;
};

export function KnowledgeRetrievalPanel({ canManage, onChange }: Props) {
  const [settings, setSettings] = useState<KnowledgeRetrievalSettingsApi | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void getKnowledgeRetrievalSettings()
      .then((row) => {
        setSettings(row);
        onChange?.(row);
      })
      .catch(() => {
        const defaults: KnowledgeRetrievalSettingsApi = {
          only_approved: true,
          include_histories: true,
          min_confidence: 0.25,
          max_sources: 5,
          project: null,
          department: null,
        };
        setSettings(defaults);
        onChange?.(defaults);
      });
    // Load org defaults once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!settings) return null;

  const save = async (patch: Partial<KnowledgeRetrievalSettingsApi>) => {
    if (!canManage) return;
    setSaving(true);
    try {
      const next = await updateKnowledgeRetrievalSettings(patch);
      setSettings(next);
      onChange?.(next);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-md border border-border/70 bg-secondary/40 p-3">
      <div className="mb-3 flex items-center gap-2">
        <Settings2 className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-foreground">Retrieval settings</span>
        {!canManage && <span className="text-[10px] text-muted-foreground">(read-only)</span>}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <input
            type="checkbox"
            checked={settings.only_approved}
            disabled={!canManage || saving}
            onChange={(e) => void save({ only_approved: e.target.checked })}
          />
          Only approved docs
        </label>
        <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <input
            type="checkbox"
            checked={settings.include_histories}
            disabled={!canManage || saving}
            onChange={(e) => void save({ include_histories: e.target.checked })}
          />
          Include histories
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Minimum confidence</span>
          <Input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={settings.min_confidence}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            onChange={(e) => void save({ min_confidence: Number(e.target.value) })}
          />
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Max sources</span>
          <Select
            value={String(settings.max_sources)}
            disabled={!canManage || saving}
            onValueChange={(value) => void save({ max_sources: Number(value) })}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[3, 5, 7, 10].map((n) => (
                <SelectItem key={n} value={String(n)}>{n}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Project filter</span>
          <Input
            value={settings.project ?? ""}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            placeholder="Any project"
            onBlur={(e) => void save({ project: e.target.value || null })}
          />
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Department filter</span>
          <Input
            value={settings.department ?? ""}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            placeholder="Any department"
            onBlur={(e) => void save({ department: e.target.value || null })}
          />
        </label>
      </div>
      {canManage && (
        <p className="mt-2 text-[10px] text-muted-foreground">Leadership and super admins can update org-wide retrieval defaults.</p>
      )}
    </div>
  );
}

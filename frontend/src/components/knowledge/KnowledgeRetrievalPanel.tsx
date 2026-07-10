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
  const [error, setError] = useState<string | null>(null);

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
          min_relevance: 0.25,
          min_confidence: 0.25,
          max_sources: 5,
          max_candidates: 20,
          project: null,
          department: null,
          source_types: [],
          folder_ids: [],
          recency_preference: 0.5,
          exact_term_preference: 0.5,
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
    const merged = { ...settings, ...patch };
    if (merged.max_sources < 1 || merged.max_sources > 10) {
      setError("Max sources must be between 1 and 10.");
      return;
    }
    if (merged.max_candidates < merged.max_sources) {
      setError("Max candidates must be greater than or equal to max sources.");
      return;
    }
    if (merged.min_relevance < 0 || merged.min_relevance > 1 || merged.min_confidence < 0 || merged.min_confidence > 1) {
      setError("Minimum relevance and confidence must be between 0 and 1.");
      return;
    }
    setError(null);
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
            checked
            disabled
            readOnly
          />
          Only approved, ready, indexed docs enforced
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
          <span>Minimum relevance</span>
          <Input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={settings.min_relevance}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            onChange={(e) => void save({ min_relevance: Number(e.target.value) })}
          />
          <span className="block text-[10px]">Filters out weak chunks before answer generation.</span>
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
          <span className="block text-[10px]">Keeps low-confidence answers visible as gaps.</span>
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
                <SelectItem key={n} value={String(n)}>
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Max candidates</span>
          <Input
            type="number"
            min={settings.max_sources}
            max={80}
            value={settings.max_candidates}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            onChange={(e) => void save({ max_candidates: Number(e.target.value) })}
          />
          <span className="block text-[10px]">Candidate pool before ranking and diversification.</span>
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
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Source types</span>
          <Input
            value={(settings.source_types ?? []).join(", ")}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            placeholder="Any source type"
            onBlur={(e) =>
              void save({
                source_types: e.target.value
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Folder IDs</span>
          <Input
            value={(settings.folder_ids ?? []).join(", ")}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            placeholder="Any folder"
            onBlur={(e) =>
              void save({
                folder_ids: e.target.value
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Recency preference</span>
          <Input
            type="number"
            min={0}
            max={1}
            step={0.1}
            value={settings.recency_preference}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            onChange={(e) => void save({ recency_preference: Number(e.target.value) })}
          />
        </label>
        <label className="space-y-1 text-[11px] text-muted-foreground">
          <span>Exact-term preference</span>
          <Input
            type="number"
            min={0}
            max={1}
            step={0.1}
            value={settings.exact_term_preference}
            disabled={!canManage || saving}
            className="h-8 text-xs"
            onChange={(e) => void save({ exact_term_preference: Number(e.target.value) })}
          />
        </label>
      </div>
      {error && <p className="mt-2 text-[10px] text-destructive">{error}</p>}
      {canManage && (
        <p className="mt-2 text-[10px] text-muted-foreground">
          Leadership and super admins can update org-wide retrieval defaults. Approval, indexing, readiness, and client-safe restrictions always apply.
        </p>
      )}
    </div>
  );
}

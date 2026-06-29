import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { GovernanceFilters } from "./filters";

type Option = { value: string; label: string };

type GovernanceFiltersBarProps = {
  filters: GovernanceFilters;
  onChange: (next: GovernanceFilters) => void;
  projects: Option[];
  users: Option[];
  showInternalFilters: boolean;
};

function FilterSelect({
  label,
  value,
  options,
  onValueChange,
}: {
  label: string;
  value: string;
  options: Option[];
  onValueChange: (value: string) => void;
}) {
  return (
    <div className="min-w-[140px] flex-1">
      <Label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger className="h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value} value={opt.value} className="text-xs">
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function GovernanceFiltersBar({
  filters,
  onChange,
  projects,
  users,
  showInternalFilters,
}: GovernanceFiltersBarProps) {
  const patch = (partial: Partial<GovernanceFilters>) => onChange({ ...filters, ...partial });

  const allOption = { value: "all", label: "All" };

  return (
    <div className="space-y-3 rounded-md border border-border bg-elevated p-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[200px] flex-[2]">
          <Label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
            Search
          </Label>
          <Input
            className="h-8 text-xs"
            placeholder="Title or project…"
            value={filters.search}
            onChange={(e) => patch({ search: e.target.value })}
          />
        </div>
        <FilterSelect
          label="Project"
          value={filters.projectId}
          options={[allOption, ...projects]}
          onValueChange={(projectId) => patch({ projectId })}
        />
        {showInternalFilters && (
          <>
            <FilterSelect
              label="Status"
              value={filters.status}
              options={[
                allOption,
                { value: "open", label: "Open" },
                { value: "blocking", label: "Blocking" },
                { value: "resolved", label: "Resolved" },
                { value: "in_progress", label: "In Progress" },
                { value: "completed", label: "Completed" },
                { value: "overdue", label: "Overdue" },
              ]}
              onValueChange={(status) => patch({ status })}
            />
            <FilterSelect
              label="Dependency type"
              value={filters.dependencyType}
              options={[
                allOption,
                { value: "client_action", label: "Client Action" },
                { value: "internal", label: "Internal" },
                { value: "external", label: "External" },
              ]}
              onValueChange={(dependencyType) => patch({ dependencyType })}
            />
            <FilterSelect
              label="Owner"
              value={filters.ownerId}
              options={[allOption, ...users]}
              onValueChange={(ownerId) => patch({ ownerId })}
            />
            <FilterSelect
              label="Scope status"
              value={filters.scopeStatus}
              options={[
                allOption,
                { value: "approved", label: "Approved" },
                { value: "pending_revision", label: "Pending Revision" },
                { value: "locked", label: "Locked" },
              ]}
              onValueChange={(scopeStatus) => patch({ scopeStatus })}
            />
          </>
        )}
        <FilterSelect
          label="Severity"
          value={filters.severity}
          options={[
            allOption,
            { value: "low", label: "Low" },
            { value: "medium", label: "Medium" },
            { value: "high", label: "High" },
            { value: "critical", label: "Critical" },
          ]}
          onValueChange={(severity) => patch({ severity })}
        />
        <FilterSelect
          label="Assignee"
          value={filters.assigneeId}
          options={[allOption, ...users]}
          onValueChange={(assigneeId) => patch({ assigneeId })}
        />
        {showInternalFilters && (
          <div className="min-w-[140px] flex-1">
            <Label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
              Due before
            </Label>
            <Input
              type="date"
              className="h-8 text-xs"
              value={filters.dueBefore}
              onChange={(e) => patch({ dueBefore: e.target.value })}
            />
          </div>
        )}
      </div>
    </div>
  );
}

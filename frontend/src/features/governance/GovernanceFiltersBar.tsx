import { useEffect, useRef, useState } from "react";
import { Filter, Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { countActiveGovernanceFilters, emptyGovernanceFilters, type GovernanceFilters } from "./filters";

type Option = { value: string; label: string };

type GovernanceFiltersBarProps = {
  filters: GovernanceFilters;
  onChange: (next: GovernanceFilters) => void;
  projects: Option[];
  users: Option[];
  showInternalFilters: boolean;
};

const governanceSearchClass =
  "h-10 rounded-full border-[color:var(--brand)]/25 bg-[color:var(--brand)]/5 pl-10 text-[color:var(--brand)] shadow-none placeholder:text-[color:var(--brand)]/55 focus-visible:border-[color:var(--brand)] focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/20";

const iconButtonClass =
  "relative h-10 w-10 shrink-0 rounded-full border-[color:var(--brand)]/25 bg-[color:var(--brand)]/5 text-[color:var(--brand)] shadow-none hover:bg-[color:var(--brand)]/10";

const fieldClass = "h-8 w-full border-border bg-background text-xs shadow-none";

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
    <div>
      <Label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </Label>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger className={fieldClass}>
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

function popoverFilterCount(filters: GovernanceFilters): number {
  const total = countActiveGovernanceFilters(filters);
  return filters.search.trim() ? total - 1 : total;
}

export function GovernanceFiltersBar({
  filters,
  onChange,
  projects,
  users,
  showInternalFilters,
}: GovernanceFiltersBarProps) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const patch = (partial: Partial<GovernanceFilters>) => onChange({ ...filters, ...partial });
  const activeFilterCount = popoverFilterCount(filters);
  const hasSearch = filters.search.trim().length > 0;
  const allOption = { value: "all", label: "All" };

  useEffect(() => {
    if (searchOpen) {
      searchInputRef.current?.focus();
    }
  }, [searchOpen]);

  const clearFilters = () => {
    onChange(emptyGovernanceFilters());
    setSearchOpen(false);
  };

  const toggleSearch = () => {
    setSearchOpen((open) => !open);
  };

  const closeSearch = () => {
    window.setTimeout(() => setSearchOpen(false), 150);
  };

  return (
    <div className="flex w-full items-center gap-2">
      <div className="min-w-0 flex-1" aria-hidden />

      {searchOpen && (
        <div className="relative w-72 max-w-[calc(100vw-7rem)] shrink-0">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--brand)]" />
          <Input
            ref={searchInputRef}
            aria-label="Search governance"
            className={governanceSearchClass}
            placeholder="Search title or project…"
            value={filters.search}
            onChange={(e) => patch({ search: e.target.value })}
            onBlur={closeSearch}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                if (hasSearch) {
                  patch({ search: "" });
                }
                setSearchOpen(false);
              }
            }}
          />
        </div>
      )}

      <div className="flex shrink-0 items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="icon"
          className={iconButtonClass}
          aria-label={searchOpen ? "Close search" : "Open search"}
          title="Search"
          aria-pressed={searchOpen}
          onClick={toggleSearch}
        >
          <Search className="h-4 w-4" />
          {hasSearch && !searchOpen && (
            <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-primary" />
          )}
        </Button>

        <Popover open={filtersOpen} onOpenChange={setFiltersOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="icon"
              className={iconButtonClass}
              aria-label="Open filters"
              title="Filters"
            >
              <Filter className="h-4 w-4" />
              {activeFilterCount > 0 && (
                <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9px] font-medium text-primary-foreground">
                  {activeFilterCount}
                </span>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            className="w-[min(92vw,32rem)] border-border p-4 shadow-none"
          >
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-medium">Filter governance data</p>
              {(activeFilterCount > 0 || hasSearch) && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1 px-2 text-[10px] shadow-none"
                  onClick={clearFilters}
                >
                  <X className="h-3 w-3" />
                  Clear all
                </Button>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
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
                <div>
                  <Label className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
                    Due before
                  </Label>
                  <Input
                    type="date"
                    className={fieldClass}
                    value={filters.dueBefore}
                    onChange={(e) => patch({ dueBefore: e.target.value })}
                  />
                </div>
              )}
            </div>

            <div className="mt-4 flex justify-end">
              <Button
                type="button"
                size="sm"
                className="h-8 text-xs shadow-none"
                onClick={() => setFiltersOpen(false)}
              >
                Done
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      </div>
    </div>
  );
}

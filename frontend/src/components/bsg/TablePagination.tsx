import { Button } from "@/components/ui/button";
import { visiblePages } from "@/lib/admin-shared";
import { cn } from "@/lib/utils";

type Props = {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
};

export function TablePagination({ currentPage, totalPages, onPageChange, className }: Props) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 border-t border-border p-4 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <p className="text-center text-xs text-muted-foreground sm:text-left">
        Page {currentPage} of {totalPages}
      </p>
      <div className="flex flex-wrap items-center justify-center gap-2 sm:justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={currentPage === 1}
          onClick={() => onPageChange(Math.max(1, currentPage - 1))}
        >
          Previous
        </Button>
        {visiblePages(currentPage, totalPages).map((pageNumber, index, pages) => (
          <div key={pageNumber} className="flex items-center gap-2">
            {index > 0 && pageNumber - pages[index - 1] > 1 && (
              <span className="px-1 text-xs text-muted-foreground">…</span>
            )}
            <Button
              type="button"
              variant={pageNumber === currentPage ? "default" : "outline"}
              size="sm"
              className="min-w-8 px-2"
              onClick={() => onPageChange(pageNumber)}
            >
              {pageNumber}
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={currentPage === totalPages}
          onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

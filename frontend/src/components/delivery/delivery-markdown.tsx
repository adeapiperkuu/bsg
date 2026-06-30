import { memo, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type Props = {
  content: string;
  className?: string;
};

const MARKDOWN_TAG_PATTERN = /<\/?markdown>/gi;
const CODE_FENCE_PATTERN = /^```(?:markdown)?\s*\n?|\n?```\s*$/g;

export function sanitizeDeliveryMarkdown(content: string): string {
  return content
    .replace(MARKDOWN_TAG_PATTERN, "")
    .replace(CODE_FENCE_PATTERN, "")
    .replace(/\r\n/g, "\n")
    .trim();
}

function renderInline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <span key={index}>{part}</span>;
  });
}

function isTableRow(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.startsWith("|") && trimmed.endsWith("|");
}

function isTableSeparator(line: string): boolean {
  return /^\|?[\s:-]+\|[\s|:-]+\|?$/.test(line.trim());
}

function parseTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

type ListItem = { text: string; depth: number };

function DeliveryMarkdownComponent({ content, className }: Props) {
  // Content is already sanitized server-side (markdown tags / code fences stripped)
  // before it reaches this component, so we trust it as-is here.
  const lines = content.split("\n");
  const blocks: ReactNode[] = [];
  let listItems: ListItem[] = [];
  let listOrdered = false;
  let tableRows: string[][] = [];

  const flushList = () => {
    if (listItems.length === 0) return;
    const ListTag = listOrdered ? "ol" : "ul";

    type GroupedItem = { text: string; children: string[] };
    const grouped: GroupedItem[] = [];
    for (const item of listItems) {
      if (item.depth === 0 || grouped.length === 0) {
        grouped.push({ text: item.text, children: [] });
      } else {
        grouped[grouped.length - 1].children.push(item.text);
      }
    }

    blocks.push(
      <ListTag
        key={`list-${blocks.length}`}
        className={cn(
          "my-2 space-y-1.5 pl-4 text-[11px] leading-5 text-foreground",
          listOrdered ? "list-decimal" : "list-disc",
        )}
      >
        {grouped.map((item, index) => (
          <li key={index} className="pl-0.5">
            {renderInline(item.text)}
            {item.children.length > 0 && (
              <ul className="mt-1.5 space-y-1.5 pl-4 list-disc">
                {item.children.map((child, childIndex) => (
                  <li key={childIndex} className="pl-0.5">
                    {renderInline(child)}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ListTag>,
    );
    listItems = [];
    listOrdered = false;
  };

  const flushTable = () => {
    if (tableRows.length === 0) return;
    const [header, ...body] = tableRows;
    blocks.push(
      <div key={`table-${blocks.length}`} className="my-3 overflow-x-auto rounded-sm border border-border/60">
        <table className="w-full min-w-[200px] text-left text-[11px]">
          {header && (
            <thead className="border-b border-border/60 bg-secondary/40">
              <tr>
                {header.map((cell, index) => (
                  <th key={index} className="px-2.5 py-1.5 font-semibold text-muted-foreground">
                    {renderInline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-border/40 last:border-0">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="px-2.5 py-1.5 text-foreground">
                    {renderInline(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
    tableRows = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (!trimmed) {
      flushList();
      flushTable();
      continue;
    }

    if (trimmed === "---" || trimmed === "***") {
      flushList();
      flushTable();
      blocks.push(<hr key={`hr-${blocks.length}`} className="my-3 border-border/50" />);
      continue;
    }

    if (isTableRow(trimmed)) {
      flushList();
      if (isTableSeparator(trimmed)) continue;
      tableRows.push(parseTableRow(trimmed));
      continue;
    }

    if (tableRows.length > 0) {
      flushTable();
    }

    const h2Match = trimmed.match(/^##\s+(.+)$/);
    const h3Match = trimmed.match(/^###\s+(.+)$/);
    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    const bulletMatch = trimmed.match(/^[-*]\s+(.+)$/);
    const nestedBulletMatch = line.match(/^\s{2,}[-*]\s+(.+)$/);

    if (h2Match) {
      flushList();
      blocks.push(
        <h2
          key={`h2-${blocks.length}`}
          className="mt-4 first:mt-0 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
        >
          {renderInline(h2Match[1])}
        </h2>,
      );
      continue;
    }

    if (h3Match) {
      flushList();
      blocks.push(
        <h3
          key={`h3-${blocks.length}`}
          className="mt-3 first:mt-0 text-[11px] font-semibold text-foreground"
        >
          {renderInline(h3Match[1])}
        </h3>,
      );
      continue;
    }

    if (nestedBulletMatch) {
      listItems.push({ text: nestedBulletMatch[1], depth: 1 });
      continue;
    }

    if (orderedMatch) {
      if (listItems.length > 0 && !listOrdered) flushList();
      listOrdered = true;
      listItems.push({ text: orderedMatch[1], depth: 0 });
      continue;
    }

    if (bulletMatch) {
      if (listItems.length > 0 && listOrdered) flushList();
      listItems.push({ text: bulletMatch[1], depth: 0 });
      continue;
    }

    flushList();
    blocks.push(
      <p key={`p-${blocks.length}`} className="text-[11px] leading-5 text-foreground">
        {renderInline(trimmed)}
      </p>,
    );
  }

  flushList();
  flushTable();

  return <div className={cn("space-y-1", className)}>{blocks}</div>;
}

export const DeliveryMarkdown = memo(DeliveryMarkdownComponent);

/** Plain-text preview for typewriter animation. */
export function deliveryMarkdownPreview(content: string): string {
  return sanitizeDeliveryMarkdown(content)
    .replace(/^#{1,3}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/^\|.*\|$/gm, "")
    .replace(/^---+$/gm, "")
    .trim();
}

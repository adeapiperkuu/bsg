const MARKDOWN_TAG_PATTERN = /<\/?markdown>/gi;
const CODE_FENCE_PATTERN = /^```(?:markdown)?\s*\n?|\n?```\s*$/g;

export function sanitizeDeliveryMarkdown(content: string): string {
  return content
    .replace(MARKDOWN_TAG_PATTERN, "")
    .replace(CODE_FENCE_PATTERN, "")
    .replace(/\r\n/g, "\n")
    .trim();
}

/** Plain-text preview for typewriter animation. */
export function deliveryMarkdownPreview(content: string): string {
  return sanitizeDeliveryMarkdown(content)
    .replace(/^#{1,3}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/^\|.*\|$/gm, "")
    .replace(/^---+$/gm, "")
    .trim();
}

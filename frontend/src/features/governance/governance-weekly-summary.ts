export type GovernanceSummarySection = { heading: string; content: string };

export function parseGovernanceSummarySections(markdown: string): GovernanceSummarySection[] {
  const matches = [...markdown.matchAll(/^##\s+(?:\d+\.\s*)?(.+)$/gm)];
  if (!matches.length) {
    return [{ heading: "Executive Overview", content: markdown.trim() }];
  }
  return matches.map((match, index) => ({
    heading: match[1].trim(),
    content: markdown
      .slice((match.index ?? 0) + match[0].length, matches[index + 1]?.index ?? markdown.length)
      .trim(),
  }));
}

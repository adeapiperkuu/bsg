export type FormattedWorkforceAnswer = {
  headline: string;
  summary: string;
  keyFindings: string[];
  caution: string | null;
  dataFreshness: string | null;
  nextStep: string | null;
  groundedIn: string | null;
  parsedConfidence: string | null;
  fullText: string;
};

type ParsedSections = {
  bodyLines: string[];
  keyFindings: string[];
  caution: string | null;
  nextStep: string | null;
  groundedIn: string | null;
  parsedConfidence: string | null;
};

const PREFIX_MATCHERS: Array<{
  key: keyof Pick<ParsedSections, "caution" | "nextStep" | "groundedIn" | "parsedConfidence">;
  pattern: RegExp;
  extract: (line: string) => string;
}> = [
  {
    key: "caution",
    pattern: /^(caution|note):\s*/i,
    extract: (line) => line.replace(/^(caution|note):\s*/i, "").trim(),
  },
  {
    key: "parsedConfidence",
    pattern: /^confidence:\s*/i,
    extract: (line) =>
      line
        .replace(/^confidence:\s*/i, "")
        .trim()
        .replace(/\.$/, ""),
  },
  {
    key: "groundedIn",
    pattern: /^grounded in\s+/i,
    extract: (line) => humanizeWording(line.trim()),
  },
  {
    key: "nextStep",
    pattern:
      /^(next step|suggested next step|recommendation|suggested action|recommended action):\s*/i,
    extract: (line) =>
      line
        .replace(
          /^(next step|suggested next step|recommendation|suggested action|recommended action):\s*/i,
          "",
        )
        .trim(),
  },
];

const FINDING_PREFIX =
  /^(overloaded|underloaded|underutilized|under-utilized|underutilised|under-utilised|skill gap|training gap|sme gap|capability gap|finding|key finding):\s*/i;

export function humanizeWording(text: string): string {
  return text
    .replace(/\b(\d+)\s+team\(s\)/gi, (_, count) => {
      const value = Number(count);
      return `${value} team${value === 1 ? "" : "s"}`;
    })
    .replace(/\bteam\(s\)/gi, "teams")
    .replace(/\b(\d+)\s+workforce\s+evidence\s+record\(s\)/gi, (_, count) => {
      const value = Number(count);
      return `${value} workforce record${value === 1 ? "" : "s"}`;
    })
    .replace(/\b(\d+)\s+evidence\s+record\(s\)/gi, (_, count) => {
      const value = Number(count);
      return `${value} workforce record${value === 1 ? "" : "s"}`;
    })
    .replace(/\bevidence\s+record\(s\)/gi, "workforce records")
    .replace(/\bannotator\(s\)/gi, "annotators")
    .replace(/\s+/g, " ")
    .trim();
}

function splitAnswerLines(answerText: string): string[] {
  return answerText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseSections(lines: string[]): ParsedSections {
  const sections: ParsedSections = {
    bodyLines: [],
    keyFindings: [],
    caution: null,
    nextStep: null,
    groundedIn: null,
    parsedConfidence: null,
  };

  for (const line of lines) {
    const prefix = PREFIX_MATCHERS.find((matcher) => matcher.pattern.test(line));
    if (prefix) {
      const value = humanizeWording(prefix.extract(line));
      if (value) sections[prefix.key] = value;
      continue;
    }

    if (FINDING_PREFIX.test(line)) {
      sections.keyFindings.push(humanizeWording(line.replace(FINDING_PREFIX, "").trim()));
      continue;
    }

    sections.bodyLines.push(humanizeWording(line));
  }

  return sections;
}

function buildHeadline(answerText: string, sections: ParsedSections): string {
  if (/no underloaded teams found/i.test(answerText)) {
    return "No underloaded teams found";
  }
  if (/no overloaded teams found/i.test(answerText)) {
    return "No overloaded teams found";
  }

  if (/underloaded teams for/i.test(answerText)) {
    const underMatch = answerText.match(/(\d+)\s+team\(s\)\s+below/i);
    if (underMatch) {
      const count = Number(underMatch[1]);
      return count === 1 ? "1 team is underutilized" : `${count} teams are underutilized`;
    }
  }

  if (/overloaded teams for/i.test(answerText)) {
    const overloadMatch = answerText.match(/(\d+)\s+team\(s\)\s+at or above/i);
    if (overloadMatch) {
      const count = Number(overloadMatch[1]);
      return count === 1 ? "1 team is overloaded" : `${count} teams are overloaded`;
    }
  }

  const overloadMatch = answerText.match(/(\d+)\s+team\(s\)\s+at or above/i);
  const underMatch =
    answerText.match(/(\d+)\s+team\(s\)\s+below/i) ?? answerText.match(/and\s+(\d+)\s+below/i);
  if (overloadMatch && underMatch && /utilization for/i.test(answerText)) {
    const overCount = Number(overloadMatch[1]);
    const underCount = Number(underMatch[1]);
    if (overCount > 0 && underCount > 0) {
      return "Teams show mixed utilization";
    }
    if (overCount > 0 && underCount === 0) {
      return overCount === 1 ? "1 team is overloaded" : `${overCount} teams are overloaded`;
    }
    if (underCount > 0 && overCount === 0) {
      return underCount === 1 ? "1 team is underutilized" : `${underCount} teams are underutilized`;
    }
  }

  if (overloadMatch) {
    const count = Number(overloadMatch[1]);
    return count === 1 ? "1 team is overloaded" : `${count} teams are overloaded`;
  }

  if (underMatch && sections.keyFindings.length === 0) {
    const count = Number(underMatch[1]);
    return count === 1 ? "1 team is underutilized" : `${count} teams are underutilized`;
  }

  if (
    sections.keyFindings.some((finding) => /underutil|below.*threshold|below \d+%/i.test(finding))
  ) {
    const underloadedCount = sections.keyFindings.filter((finding) =>
      /underutil|below.*threshold|below \d+%/i.test(finding),
    ).length;
    if (underloadedCount === 1) return "1 team is underutilized";
    if (underloadedCount > 1) return `${underloadedCount} teams are underutilized`;
  }

  if (sections.keyFindings.some((finding) => /overload|above.*threshold|at \d+%/i.test(finding))) {
    const overloadedCount = sections.keyFindings.filter((finding) =>
      /overload|above.*threshold|at \d+%/i.test(finding),
    ).length;
    if (overloadedCount === 1) return "1 team is overloaded";
    if (overloadedCount > 1) return `${overloadedCount} teams are overloaded`;
  }

  const lower = answerText.toLowerCase();
  if (lower.includes("sme shortage") || lower.includes("not enough sme")) {
    return "SME coverage needs attention";
  }
  if (lower.includes("training gap")) {
    return "Training gaps need attention";
  }
  if (lower.includes("skill shortage") || lower.includes("capability gap")) {
    return "Capability gaps detected";
  }
  if (lower.includes("recommendation")) {
    return "Workforce action recommended";
  }

  const firstLine =
    sections.bodyLines[0] ?? humanizeWording(answerText.split(/\r?\n/)[0] ?? "Workforce insight");
  const sentence = firstLine.split(/(?<=[.!?])\s+/)[0] ?? firstLine;
  return sentence.length > 90 ? `${sentence.slice(0, 87)}…` : sentence;
}

function buildSummary(sections: ParsedSections, headline: string): string {
  if (sections.keyFindings.length > 0) {
    return sections.keyFindings[0]!;
  }

  const candidate = sections.bodyLines.find((line) => line !== headline);
  if (candidate) return candidate;

  return "";
}

const STALE_UTILIZATION_PATTERN =
  /\butili[sz]ation\s+(snapshot|data)\b.*\b(\d+\s+days?\s+old|stale|out of date|older than)\b/i;

export function isStaleUtilizationWarning(text: string): boolean {
  const lower = text.toLowerCase();
  if (lower.includes("no utilization snapshots")) return false;
  return (
    STALE_UTILIZATION_PATTERN.test(lower) ||
    /\b\d+\s+days?\s+old\b.*\butili[sz]ation\b/i.test(lower)
  );
}

export function formatDataFreshnessNotice(warningText: string, answerText: string): string {
  const daysMatch = warningText.match(/(\d+)\s+days?\s+old/i);
  const days = daysMatch ? Number(daysMatch[1]) : null;
  const dateMatch =
    answerText.match(/\bon\s+(\d{4}-\d{2}-\d{2})\b/i) ??
    answerText.match(/\b(\d{4}-\d{2}-\d{2})\b/);
  const snapshotDate = dateMatch?.[1];

  if (snapshotDate && days != null) {
    return `This answer is based on utilization data from ${snapshotDate}. Because it is ${days} days old, confirm the current workload before acting.`;
  }
  if (days != null) {
    return `This answer is based on utilization data that is ${days} days old. Confirm the current workload before acting.`;
  }
  return "This answer is based on utilization data that may no longer reflect the current workload. Confirm the latest figures before acting.";
}

function splitWarningSections(
  caution: string | null,
  answerText: string,
): {
  caution: string | null;
  dataFreshness: string | null;
} {
  if (!caution) {
    return { caution: null, dataFreshness: null };
  }
  if (isStaleUtilizationWarning(caution)) {
    return {
      caution: null,
      dataFreshness: formatDataFreshnessNotice(caution, answerText),
    };
  }
  return { caution, dataFreshness: null };
}

export function formatWorkforceAnswer(
  answerText: string,
  options?: { dateContext?: string },
): FormattedWorkforceAnswer {
  const lines = splitAnswerLines(answerText);
  const sections = parseSections(lines);
  const headline = buildHeadline(answerText, sections);
  const summary = buildSummary(sections, headline);
  const freshnessContext = [answerText, options?.dateContext].filter(Boolean).join("\n");
  const { caution, dataFreshness } = splitWarningSections(sections.caution, freshnessContext);

  const extraFindings =
    sections.keyFindings.length > 1
      ? sections.keyFindings.slice(1)
      : sections.bodyLines.filter((line) => line !== headline && line !== summary);

  return {
    headline,
    summary,
    keyFindings: extraFindings,
    caution,
    dataFreshness,
    nextStep: sections.nextStep,
    groundedIn: sections.groundedIn,
    parsedConfidence: sections.parsedConfidence,
    fullText: answerText,
  };
}

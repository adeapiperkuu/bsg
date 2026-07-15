import { describe, expect, it } from "vitest";

import {
  dependencyRowClass,
  isCriticalPathDependency,
} from "@/lib/governance-utils";

describe("critical path dependency helpers", () => {
  it("flags blocking overdue dependencies as critical path", () => {
    expect(isCriticalPathDependency({ status: "blocking", overdue_days: 2 })).toBe(true);
    expect(isCriticalPathDependency({ status: "blocking", overdue_days: 0 })).toBe(false);
    expect(isCriticalPathDependency({ status: "open", overdue_days: 3 })).toBe(false);
  });

  it("uses a stronger row class for critical-path rows", () => {
    const critical = dependencyRowClass({ status: "blocking", overdue_days: 4 });
    const blocking = dependencyRowClass({ status: "blocking", overdue_days: 0 });
    expect(critical).toContain("ring-");
    expect(blocking).not.toContain("ring-");
  });
});

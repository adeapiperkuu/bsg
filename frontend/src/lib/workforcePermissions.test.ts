import { describe, expect, it } from "vitest";

import { canManageWorkforce, canReadInternalWorkforce } from "@/lib/workforcePermissions";
import type { AppRole } from "@/types/auth";

describe("workforcePermissions", () => {
  it.each<[AppRole | undefined, boolean]>([
    [undefined, false],
    ["client", false],
    ["delivery_manager", true],
    ["bsg_leadership", true],
    ["super_admin", true],
  ])("canReadInternalWorkforce(%s) is %s", (role, expected) => {
    expect(canReadInternalWorkforce(role)).toBe(expected);
  });

  it.each<[AppRole | undefined, boolean]>([
    [undefined, false],
    ["client", false],
    ["delivery_manager", true],
    ["bsg_leadership", false],
    ["super_admin", true],
  ])("canManageWorkforce(%s) is %s", (role, expected) => {
    expect(canManageWorkforce(role)).toBe(expected);
  });
});

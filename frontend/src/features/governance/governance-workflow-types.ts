export type WorkflowDialogState =
  | { kind: "dependency"; mode: "create" | "edit"; projectId?: string; id?: string }
  | { kind: "action"; mode: "create" | "edit"; projectId?: string; id?: string }
  | { kind: "escalation"; mode: "create" | "edit"; projectId?: string; id?: string }
  | { kind: "scope"; mode: "edit"; projectId: string }
  | null;

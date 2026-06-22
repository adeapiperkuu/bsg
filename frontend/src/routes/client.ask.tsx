import { createFileRoute } from "@tanstack/react-router";
import { Card, SectionHeader, AiBadge } from "@/components/bsg/widgets";
import { useState } from "react";

export const Route = createFileRoute("/client/ask")({ component: Ask });

function Ask() {
  type Msg = { role: "ai" | "user"; text: string };
  const [m, setM] = useState<Msg[]>([{ role: "ai", text: "Hi — I can answer questions about your projects, milestones and reports. Anything outside that scope will be routed to your BSG PM." }]);
  const [v, setV] = useState("");
  const send = () => {
    if (!v.trim()) return;
    setM((p) => [...p, { role: "user", text: v }, { role: "ai", text: "Based on this week's data, your batch 14 is on track for Jun 24 delivery with 94% confidence." }]);
    setV("");
  };
  return (
    <Card>
      <SectionHeader title="Ask Agent" sub="Restricted to your projects" right={<AiBadge confidence={91} />} />
      <div className="mb-3 max-h-[420px] space-y-2 overflow-y-auto">
        {m.map((x, i) => (
          <div key={i} className={x.role === "ai" ? "rounded-md border border-border bg-elevated p-3 text-xs" : "rounded-md bg-[color:var(--brand)]/10 p-3 text-xs"}><div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{x.role === "ai" ? "BSG Agent" : "You"}</div><div>{x.text}</div></div>
        ))}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex gap-2"><input value={v} onChange={(e) => setV(e.target.value)} placeholder="Ask about your project…" className="flex-1 rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none focus:border-[color:var(--brand)]" /><button className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]">Send</button></form>
    </Card>
  );
}

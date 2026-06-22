import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card, SectionHeader, AiBadge } from "@/components/bsg/widgets";
import { FileText, Folder, ChevronRight } from "lucide-react";

export const Route = createFileRoute("/knowledge")({ component: KnowledgePage });

const tree = [
  { folder: "SOPs", items: ["Annotation Protocol v4", "QA Sign-off Process", "Escalation Playbook"] },
  { folder: "Guides", items: ["Guideline v3 (NLP)", "Radiology Lesion Atlas", "Voice Transcription Rubric"] },
  { folder: "Histories", items: ["Aurora Project Postmortem", "Helios Schema Evolution", "Orion Region Delivery Log"] },
];

function KnowledgePage() {
  const [doc, setDoc] = useState<string | null>("Annotation Protocol v4");
  return (
    <div className="grid grid-cols-12 gap-5">
      <Card className="col-span-3">
        <SectionHeader title="Knowledge Base" sub="Browse documents" />
        <div className="space-y-3 text-xs">
          {tree.map((g) => (
            <div key={g.folder}>
              <div className="mb-1 flex items-center gap-1.5 font-medium text-muted-foreground"><Folder className="h-3.5 w-3.5" />{g.folder}</div>
              <ul className="ml-4 space-y-0.5">
                {g.items.map((i) => (
                  <li key={i}>
                    <button onClick={() => setDoc(i)} className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left hover:bg-elevated ${doc === i ? "bg-elevated text-foreground" : "text-muted-foreground"}`}>
                      <FileText className="h-3 w-3" /> {i}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Card>

      <Card className="col-span-5">
        <SectionHeader title="Ask Knowledge Agent" sub="Cited answers from your SOPs and guides" right={<AiBadge confidence={92} />} />
        <div className="space-y-3 text-xs">
          <div className="rounded-md bg-[color:var(--brand)]/10 p-3"><span className="text-[10px] uppercase tracking-wider text-muted-foreground">You</span><div className="mt-1">What's our policy on reviewer calibration after IAA drift?</div></div>
          <div className="rounded-md border border-border bg-elevated p-3">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Knowledge Agent</span>
            <p className="mt-1 leading-5">Per SOP §4.2, a calibration session must be triggered within 3 business days of any sustained IAA dip below 0.85 across two consecutive batches. Reviewers re-annotate a golden subset; results are compared via Krippendorff's α.</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button onClick={() => setDoc("QA Sign-off Process")} className="rounded border border-border bg-card px-2 py-0.5 text-[10px] hover:bg-elevated">📎 SOP — Annotation Protocol v4 §4.2</button>
              <button onClick={() => setDoc("Radiology Lesion Atlas")} className="rounded border border-border bg-card px-2 py-0.5 text-[10px] hover:bg-elevated">📎 Radiology Lesion Atlas p.18</button>
            </div>
          </div>
        </div>
        <form className="mt-4 flex gap-2"><input placeholder="Ask the knowledge base…" className="flex-1 rounded border border-border bg-card px-2.5 py-1.5 text-xs outline-none focus:border-[color:var(--brand)]" /><button className="rounded bg-[color:var(--brand)] px-3 py-1.5 text-xs font-medium text-[color:var(--brand-foreground)]">Ask</button></form>
      </Card>

      <Card className="col-span-4">
        <SectionHeader title={doc ?? "Document Preview"} sub="Embedded preview" />
        {doc ? (
          <div className="space-y-2 rounded-md border border-border bg-elevated p-4 text-xs leading-5">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{doc} · v4.2 · Updated Jun 11</div>
            <h4 className="text-sm font-semibold">§4.2 Reviewer Calibration</h4>
            <p>Whenever IAA falls below the configured operating threshold (default 0.85), the Quality Agent will auto-issue a calibration ticket. SMEs convene within 72 hours and re-annotate a curated golden subset.</p>
            <p>{`The Krippendorff α from re-annotation is logged and compared against historical baselines. Variance > 0.05 triggers a guideline revision request.`}</p>
            <h4 className="mt-2 text-sm font-semibold">§4.3 Drift Reporting</h4>
            <p>Drift incidents are surfaced in the Quality Intelligence dashboard with full evidence trail (batch IDs, annotator IDs, sample inputs).</p>
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-border p-6 text-center text-xs text-muted-foreground">Select a document from the tree.</div>
        )}
      </Card>
    </div>
  );
}

import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card, SectionHeader } from "@/components/bsg/widgets";
import { Folder, FileText, Search } from "lucide-react";

export const Route = createFileRoute("/documents")({ component: DocsPage });

const folders = ["Contracts", "SOPs", "Client Reports", "Audits", "Training Material"];
const docs = [
  { name: "MSA — Aurora Health.pdf", folder: "Contracts", size: "412 KB", modified: "Jun 12" },
  { name: "SOP — Annotation v4.docx", folder: "SOPs", size: "188 KB", modified: "Jun 11" },
  { name: "W24 — Aurora weekly.pdf", folder: "Client Reports", size: "812 KB", modified: "Jun 17" },
  { name: "ISO 27001 — Audit Q2.pdf", folder: "Audits", size: "2.1 MB", modified: "Jun 09" },
  {
    name: "Radiology calibration deck.pptx",
    folder: "Training Material",
    size: "5.4 MB",
    modified: "Jun 05",
  },
  { name: "NDA Addendum — Vertex.pdf", folder: "Contracts", size: "98 KB", modified: "Jun 14" },
];

function DocsPage() {
  const [sel, setSel] = useState(docs[0]);
  return (
    <div className="grid grid-cols-12 gap-5">
      <Card className="col-span-2">
        <SectionHeader title="Folders" />
        <ul className="space-y-0.5 text-xs">
          {folders.map((f) => (
            <li key={f}>
              <button className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left hover:bg-elevated">
                <Folder className="h-3.5 w-3.5" />
                {f}
              </button>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="col-span-6">
        <div className="mb-3 flex items-center gap-2 rounded-md border border-border bg-elevated px-2 py-1.5 text-xs">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input placeholder="Search documents…" className="flex-1 bg-transparent outline-none" />
        </div>
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 font-medium">Name</th>
              <th className="py-2 pr-3 font-medium">Folder</th>
              <th className="py-2 pr-3 font-medium">Size</th>
              <th className="py-2 pr-3 font-medium">Modified</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr
                key={d.name}
                onClick={() => setSel(d)}
                className={`cursor-pointer border-b border-border/50 hover:bg-elevated ${sel.name === d.name ? "bg-elevated" : ""}`}
              >
                <td className="py-2.5 pr-3 font-medium">
                  <span className="inline-flex items-center gap-1.5">
                    <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                    {d.name}
                  </span>
                </td>
                <td className="py-2.5 pr-3 text-muted-foreground">{d.folder}</td>
                <td className="py-2.5 pr-3">{d.size}</td>
                <td className="py-2.5 pr-3 text-muted-foreground">{d.modified}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card className="col-span-4">
        <SectionHeader title="Preview" sub={sel.name} />
        <div className="rounded-md border border-border bg-elevated p-5 text-xs leading-5">
          <div className="mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            {sel.folder} · {sel.size} · Modified {sel.modified}
          </div>
          <h4 className="mb-2 text-sm font-semibold">{sel.name}</h4>
          <p>
            This is a preview of the document. The full file would render here using an embedded
            viewer (PDF, DOCX, etc.).
          </p>
          <p className="mt-2 text-muted-foreground">— BSG Confidential —</p>
        </div>
      </Card>
    </div>
  );
}

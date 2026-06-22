import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Card, SectionHeader, StatusPill } from "@/components/bsg/widgets";
import { projects } from "@/lib/bsg/data";
import { LayoutGrid, List, Search } from "lucide-react";

export const Route = createFileRoute("/projects")({ component: ProjectsPage });

function ProjectsPage() {
  const [view, setView] = useState<"table" | "cards">("table");
  const [open, setOpen] = useState<string | null>(null);
  const project = projects.find((p) => p.id === open);

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-1 items-center gap-2 rounded-md border border-border bg-elevated px-2.5 py-1.5 text-xs">
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
            <input placeholder="Search projects…" className="flex-1 bg-transparent outline-none" />
          </div>
          <select className="rounded border border-border bg-card px-2 py-1.5 text-xs"><option>Status: All</option><option>On Track</option><option>At Risk</option><option>Critical</option></select>
          <select className="rounded border border-border bg-card px-2 py-1.5 text-xs"><option>Client: All</option><option>Aurora Health</option><option>Helios Bank</option></select>
          <select className="rounded border border-border bg-card px-2 py-1.5 text-xs"><option>Region: All</option><option>India</option><option>Kosovo</option></select>
          <div className="flex rounded-md border border-border bg-elevated p-0.5">
            <button onClick={() => setView("table")} className={`rounded p-1 ${view === "table" ? "bg-card" : ""}`}><List className="h-3.5 w-3.5" /></button>
            <button onClick={() => setView("cards")} className={`rounded p-1 ${view === "cards" ? "bg-card" : ""}`}><LayoutGrid className="h-3.5 w-3.5" /></button>
          </div>
        </div>
      </Card>

      {view === "table" ? (
        <Card>
          <table className="w-full text-xs">
            <thead className="text-left text-muted-foreground"><tr className="border-b border-border">
              <th className="py-2 pr-3 font-medium">ID</th>
              <th className="py-2 pr-3 font-medium">Project</th>
              <th className="py-2 pr-3 font-medium">Client</th>
              <th className="py-2 pr-3 font-medium">Region</th>
              <th className="py-2 pr-3 font-medium">Throughput</th>
              <th className="py-2 pr-3 font-medium">Confidence</th>
              <th className="py-2 pr-3 font-medium">Risk</th>
              <th className="py-2 pr-3 font-medium">Milestone</th>
            </tr></thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="cursor-pointer border-b border-border/50 hover:bg-elevated" onClick={() => setOpen(p.id)}>
                  <td className="py-2.5 pr-3 text-muted-foreground">{p.id}</td>
                  <td className="py-2.5 pr-3 font-medium">{p.name}</td>
                  <td className="py-2.5 pr-3">{p.client}</td>
                  <td className="py-2.5 pr-3">{p.region}</td>
                  <td className="py-2.5 pr-3">{p.throughput}/d</td>
                  <td className="py-2.5 pr-3">{p.confidence}%</td>
                  <td className="py-2.5 pr-3"><StatusPill status={p.risk} /></td>
                  <td className="py-2.5 pr-3 text-muted-foreground">{p.milestone}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((p) => (
            <Card key={p.id}>
              <div className="flex items-start justify-between">
                <div><div className="text-sm font-semibold">{p.name}</div><div className="text-[11px] text-muted-foreground">{p.client} · {p.region}</div></div>
                <StatusPill status={p.risk} />
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                <div><dt className="text-muted-foreground">Throughput</dt><dd className="font-medium">{p.throughput}/d</dd></div>
                <div><dt className="text-muted-foreground">Confidence</dt><dd className="font-medium">{p.confidence}%</dd></div>
                <div className="col-span-2"><dt className="text-muted-foreground">Next milestone</dt><dd>{p.milestone}</dd></div>
              </dl>
              <button onClick={() => setOpen(p.id)} className="mt-3 w-full rounded border border-border py-1 text-[11px] hover:bg-elevated">View detail</button>
            </Card>
          ))}
        </div>
      )}

      {project && (
        <div className="fixed inset-0 z-40 flex justify-end bg-background/60 backdrop-blur-sm" onClick={() => setOpen(null)}>
          <div className="h-full w-full max-w-xl overflow-y-auto border-l border-border bg-card p-6" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between">
              <div><div className="text-lg font-semibold">{project.name}</div><div className="text-xs text-muted-foreground">{project.client} · {project.region} · {project.id}</div></div>
              <button onClick={() => setOpen(null)} className="rounded border border-border px-2 py-1 text-xs">Close</button>
            </div>
            <div className="grid grid-cols-3 gap-3 text-xs">
              <div className="rounded border border-border bg-elevated p-3"><div className="text-[10px] uppercase text-muted-foreground">Throughput</div><div className="text-base font-semibold">{project.throughput}/d</div></div>
              <div className="rounded border border-border bg-elevated p-3"><div className="text-[10px] uppercase text-muted-foreground">Confidence</div><div className="text-base font-semibold">{project.confidence}%</div></div>
              <div className="rounded border border-border bg-elevated p-3"><div className="text-[10px] uppercase text-muted-foreground">Risk</div><div className="mt-1"><StatusPill status={project.risk} /></div></div>
            </div>
            <div className="mt-5">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Milestone timeline</div>
              <ol className="relative border-l border-border pl-4 text-xs">
                {["Kickoff", "Schema sign-off", "Batch 12 QA", project.milestone, "Final delivery"].map((m, i) => (
                  <li key={m} className="mb-3"><span className="absolute -left-1.5 h-3 w-3 rounded-full bg-[color:var(--brand)]" /><div className="font-medium">{m}</div><div className="text-[10px] text-muted-foreground">{i < 3 ? "Completed" : i === 3 ? "In Progress" : "Upcoming"}</div></li>
                ))}
              </ol>
            </div>
            <div className="mt-5">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Team roster</div>
              <ul className="grid grid-cols-2 gap-2 text-xs">
                {["Maya Chen · PM", "Priya R. · Lead Annotator", "Arben K. · QA", "Dr. R. Iyer · SME"].map((m) => (
                  <li key={m} className="rounded border border-border bg-elevated px-2.5 py-1.5">{m}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

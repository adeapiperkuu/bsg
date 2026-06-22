// Synthetic operational data for BSG Insights Hub

export const kpis = {
  activeProjects: 28,
  scheduleConfidence: 87,
  openEscalations: 6,
  avgQualityScore: 94.2,
};

export const projects = [
  { id: "P-1042", name: "Aurora Vision Labeling", client: "Aurora Health", region: "India", throughput: 1240, confidence: 92, risk: "Low", lastUpdated: "2h ago", milestone: "Batch 14 QA" },
  { id: "P-1051", name: "Helios Doc Extraction", client: "Helios Bank", region: "Kosovo", throughput: 860, confidence: 74, risk: "Medium", lastUpdated: "1h ago", milestone: "Schema sign-off" },
  { id: "P-1067", name: "Nimbus NLP Curation", client: "Nimbus AI", region: "India", throughput: 540, confidence: 61, risk: "High", lastUpdated: "12m ago", milestone: "Guideline v3 review" },
  { id: "P-1078", name: "Orion Satellite Tagging", client: "Orion Geo", region: "Kosovo", throughput: 1820, confidence: 95, risk: "Low", lastUpdated: "30m ago", milestone: "Region 4 delivery" },
  { id: "P-1083", name: "Pulse Medical Imaging", client: "Pulse Diagnostics", region: "India", throughput: 410, confidence: 68, risk: "High", lastUpdated: "5m ago", milestone: "Calibration round" },
  { id: "P-1090", name: "Vertex Finance Docs", client: "Vertex Capital", region: "Kosovo", throughput: 990, confidence: 88, risk: "Low", lastUpdated: "45m ago", milestone: "Compliance audit" },
  { id: "P-1101", name: "Lumen Retail Catalog", client: "Lumen Retail", region: "India", throughput: 1320, confidence: 90, risk: "Low", lastUpdated: "1h ago", milestone: "SKU batch 22" },
  { id: "P-1112", name: "Falcon Voice Transcription", client: "Falcon Telecom", region: "Kosovo", throughput: 670, confidence: 79, risk: "Medium", lastUpdated: "3h ago", milestone: "QA round 2" },
];

export const riskTrend = Array.from({ length: 8 }, (_, i) => ({
  week: `W${i + 17}`,
  Aurora: 18 + Math.round(Math.sin(i) * 4),
  Helios: 32 + i * 2,
  Nimbus: 48 + Math.round(Math.cos(i) * 6) + i,
  Orion: 12 + Math.round(Math.sin(i / 2) * 3),
}));

export const qualityTrend = Array.from({ length: 12 }, (_, i) => ({
  week: `W${i + 13}`,
  goldAccuracy: 95 + Math.round(Math.sin(i / 2) * 2) - (i > 8 ? (i - 8) : 0),
  iaa: 0.88 + Math.sin(i / 3) * 0.04 - (i > 8 ? (i - 8) * 0.01 : 0),
}));

export const utilization = [
  { team: "India · Medical", value: 92 },
  { team: "India · Finance", value: 78 },
  { team: "India · NLP", value: 88 },
  { team: "Kosovo · Geo", value: 84 },
  { team: "Kosovo · Voice", value: 71 },
  { team: "Kosovo · Docs", value: 95 },
];

export const alerts = [
  { sev: "Critical", project: "Pulse Medical Imaging", desc: "IAA dropped below 0.82 threshold across radiology subset", ts: "12m ago" },
  { sev: "Critical", project: "Nimbus NLP Curation", desc: "Schedule confidence at 61% — 2 dependencies blocking", ts: "47m ago" },
  { sev: "Warning", project: "Helios Doc Extraction", desc: "Rework rate up 8% week-over-week", ts: "1h ago" },
  { sev: "Warning", project: "Falcon Voice Transcription", desc: "Two annotators flagged for calibration drift", ts: "2h ago" },
  { sev: "Warning", project: "Vertex Finance Docs", desc: "Client awaiting response on schema clarification (3d)", ts: "3h ago" },
];

export const recommendations = [
  { title: "Re-allocate 4 SMEs from Lumen to Pulse Medical Imaging", confidence: 91, evidence: 7, priority: "High" },
  { title: "Trigger calibration session for Nimbus NLP team (guideline v3)", confidence: 86, evidence: 5, priority: "High" },
  { title: "Escalate Helios schema sign-off to client governance call", confidence: 78, evidence: 4, priority: "Medium" },
  { title: "Shift Orion Region 4 review window by 48h to free QA capacity", confidence: 72, evidence: 3, priority: "Medium" },
];

export const milestones = [
  { project: "Aurora Vision", name: "Batch 14 QA Sign-off", due: "Jun 24", confidence: 94, status: "On Track" },
  { project: "Helios Docs", name: "Schema v2 Approval", due: "Jun 25", confidence: 72, status: "At Risk" },
  { project: "Nimbus NLP", name: "Guideline v3 Roll-out", due: "Jun 26", confidence: 58, status: "Critical" },
  { project: "Orion Geo", name: "Region 4 Delivery", due: "Jun 27", confidence: 96, status: "On Track" },
  { project: "Pulse Medical", name: "Calibration Round 2", due: "Jun 28", confidence: 65, status: "At Risk" },
  { project: "Vertex Finance", name: "Compliance Audit", due: "Jul 01", confidence: 89, status: "On Track" },
];

export const activity = [
  { ts: "2m ago", actor: "Maya Chen", text: "Approved AI-drafted weekly summary for Aurora Health" },
  { ts: "14m ago", actor: "Delivery Agent", text: "Flagged Pulse Medical Imaging — IAA breach detected" },
  { ts: "37m ago", actor: "Arben K.", text: "Resolved escalation #ESC-204 (Helios schema)" },
  { ts: "1h ago", actor: "Quality Agent", text: "Generated drift narrative for Nimbus NLP" },
  { ts: "2h ago", actor: "Priya R.", text: "Re-assigned 3 reviewers from Lumen to Pulse" },
  { ts: "3h ago", actor: "Client Portal", text: "Vertex Capital downloaded weekly report W23" },
  { ts: "4h ago", actor: "Workforce Agent", text: "Detected SME capacity gap in radiology domain" },
  { ts: "5h ago", actor: "Governance Agent", text: "Auto-drafted governance pack for tomorrow's call" },
  { ts: "6h ago", actor: "Sara L.", text: "Closed 4 action items from last week's review" },
  { ts: "7h ago", actor: "PM Console", text: "Submitted 2 reports for client approval" },
];

export const healthDistribution = [
  { name: "On Track", value: 19, color: "#22c55e" },
  { name: "At Risk", value: 6, color: "#f59e0b" },
  { name: "Critical", value: 3, color: "#ef4444" },
];

export const rootCauses = [
  { cause: "Absenteeism (India · Medical)", impact: 34 },
  { cause: "Rework rate spike (Pulse)", impact: 26 },
  { cause: "Reviewer turnaround > SLA", impact: 22 },
  { cause: "Resource overload (Nimbus)", impact: 18 },
];

export const confidenceForecast = Array.from({ length: 20 }, (_, i) => ({
  week: `W${i + 9}`,
  confidence: i < 16 ? 78 + Math.round(Math.sin(i / 2) * 6) : null,
  forecast: i >= 15 ? 78 + Math.round(Math.sin(i / 2) * 6) - (i - 15) * 2 : null,
}));

export const errorCategories = [
  { cat: "Boundary Precision", count: 142, delta: "+12%" },
  { cat: "Class Confusion", count: 98, delta: "-4%" },
  { cat: "Guideline Ambiguity", count: 76, delta: "+8%" },
  { cat: "Missing Label", count: 54, delta: "-2%" },
  { cat: "Over-labeling", count: 31, delta: "+1%" },
];

export const teamScorecard = [
  { team: "Radiology Pod A", annotators: 18, gold: 96.2, iaa: 0.91, rework: 4.1, status: "Green" },
  { team: "Radiology Pod B", annotators: 14, gold: 88.4, iaa: 0.81, rework: 11.2, status: "Red" },
  { team: "Finance Docs", annotators: 22, gold: 94.7, iaa: 0.88, rework: 5.4, status: "Green" },
  { team: "NLP Curation", annotators: 16, gold: 90.1, iaa: 0.84, rework: 8.6, status: "Amber" },
  { team: "Geo Tagging", annotators: 12, gold: 97.5, iaa: 0.93, rework: 2.7, status: "Green" },
  { team: "Voice Transcription", annotators: 19, gold: 91.8, iaa: 0.86, rework: 6.9, status: "Amber" },
];

export const skillMatrix = [
  { domain: "Medical Imaging", India: "High", Kosovo: "Low" },
  { domain: "Financial Documents", India: "Medium", Kosovo: "High" },
  { domain: "NLP / Text", India: "High", Kosovo: "Medium" },
  { domain: "Geospatial", India: "Low", Kosovo: "High" },
  { domain: "Voice / Audio", India: "Medium", Kosovo: "High" },
  { domain: "Retail / Catalog", India: "High", Kosovo: "Medium" },
];

export const smeAllocation = [
  { name: "Dr. R. Iyer", domain: "Radiology", project: "Pulse Medical", util: 95, available: "Jul 12" },
  { name: "A. Hoxha", domain: "Financial Docs", project: "Vertex Finance", util: 82, available: "Jun 30" },
  { name: "S. Banerjee", domain: "NLP", project: "Nimbus NLP", util: 100, available: "Aug 01" },
  { name: "L. Krasniqi", domain: "Geospatial", project: "Orion Geo", util: 74, available: "Jul 05" },
  { name: "P. Sharma", domain: "Retail", project: "Lumen Retail", util: 68, available: "Jun 28" },
];

export const dependencies = [
  { name: "Client schema v2 approval", type: "Client action", project: "Helios Docs", owner: "Helios IT", overdue: 4, status: "Blocking" },
  { name: "Annotation tool upgrade", type: "Internal", project: "Pulse Medical", owner: "Platform Team", overdue: 0, status: "In Progress" },
  { name: "GPU quota uplift", type: "External", project: "Nimbus NLP", owner: "CloudOps", overdue: 2, status: "Blocking" },
  { name: "Legal review of NDA addendum", type: "Internal", project: "Vertex Finance", owner: "Legal", overdue: 0, status: "Resolved" },
  { name: "Reviewer training session", type: "Internal", project: "Falcon Voice", owner: "L&D", overdue: 1, status: "In Progress" },
];

export const escalations = [
  { title: "IAA drift on radiology subset", project: "Pulse Medical", severity: "Critical", raisedBy: "Quality Agent", date: "Jun 18", status: "Open", assigned: "Maya Chen", notes: "Calibration round scheduled for Jun 22." },
  { title: "Schema sign-off delay", project: "Helios Docs", severity: "High", raisedBy: "Arben K.", date: "Jun 17", status: "In Progress", assigned: "Client PM", notes: "Awaiting Helios IT response." },
  { title: "Capacity shortfall NLP", project: "Nimbus NLP", severity: "High", raisedBy: "Workforce Agent", date: "Jun 16", status: "Open", assigned: "Priya R.", notes: "Considering 4-SME re-allocation." },
  { title: "Reviewer turnover Voice", project: "Falcon Voice", severity: "Medium", raisedBy: "Sara L.", date: "Jun 15", status: "Resolved", assigned: "Sara L.", notes: "Backfill complete." },
];

export const clients = [
  { name: "Aurora Health", projects: 3, health: "On Track", confidence: 92, lastReport: "Jun 17", nextMilestone: "Jun 24", csat: 5 },
  { name: "Helios Bank", projects: 2, health: "At Risk", confidence: 74, lastReport: "Jun 16", nextMilestone: "Jun 25", csat: 4 },
  { name: "Nimbus AI", projects: 1, health: "Critical", confidence: 61, lastReport: "Jun 14", nextMilestone: "Jun 26", csat: 3 },
  { name: "Orion Geo", projects: 4, health: "On Track", confidence: 95, lastReport: "Jun 18", nextMilestone: "Jun 27", csat: 5 },
  { name: "Pulse Diagnostics", projects: 2, health: "At Risk", confidence: 68, lastReport: "Jun 15", nextMilestone: "Jun 28", csat: 4 },
  { name: "Vertex Capital", projects: 3, health: "On Track", confidence: 88, lastReport: "Jun 18", nextMilestone: "Jul 01", csat: 5 },
  { name: "Lumen Retail", projects: 2, health: "On Track", confidence: 90, lastReport: "Jun 17", nextMilestone: "Jun 30", csat: 5 },
  { name: "Falcon Telecom", projects: 1, health: "At Risk", confidence: 79, lastReport: "Jun 16", nextMilestone: "Jun 29", csat: 4 },
];

export const aiSummary = `Portfolio is operating at 87% schedule confidence, in line with the rolling 4-week average. Eight projects across India and Kosovo are tracking green, while Pulse Medical Imaging and Nimbus NLP Curation have moved into the high-risk band following IAA drift in radiology and a capacity shortfall in NLP curation respectively.

Quality posture remains strong overall (gold-set accuracy 94.2%), but a 2.1 point dip in inter-annotator agreement on Pulse warrants reviewer recalibration before next week's batch. Three governance items are due before Friday's client call, all auto-drafted by the Governance Agent and pending PM approval.

Recommended this week: reallocate 4 SMEs from Lumen to Pulse, trigger guideline v3 calibration on Nimbus, and escalate Helios schema sign-off into the client governance agenda. Expected impact: schedule confidence recovery to 90%+ within 2 weeks.`;

export const notifications = [
  { title: "IAA breach — Pulse Medical", time: "12m ago", sev: "Critical" },
  { title: "Helios schema awaiting client", time: "1h ago", sev: "Warning" },
  { title: "Weekly summary ready for review", time: "2h ago", sev: "Info" },
  { title: "Orion Region 4 delivered on time", time: "5h ago", sev: "Success" },
  { title: "Governance pack auto-drafted", time: "8h ago", sev: "Info" },
];

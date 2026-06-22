"""
Generates supabase/seed.sql for the BSG AI Operations Suite schema.
Run with: python generate_seed.py > seed.sql   (or it writes directly to seed.sql)

This script is NOT part of the migration/runtime — it's a one-off data generator.
"""
import random
import uuid
from datetime import date, datetime, timedelta

random.seed(42)

OUT_PATH = "seed.sql"

TODAY = date(2026, 6, 22)
START = TODAY - timedelta(days=730)  # ~2 years ago

def uid():
    return str(uuid.uuid4())

def sql_str(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"

def sql_date(d):
    return "NULL" if d is None else f"'{d.isoformat()}'"

def sql_ts(dt):
    return "NULL" if dt is None else f"'{dt.isoformat()}'"

def sql_bool(b):
    return "TRUE" if b else "FALSE"

def sql_num(n, ndigits=2):
    if n is None:
        return "NULL"
    return str(round(n, ndigits))

def sql_val(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return sql_bool(v)
    if isinstance(v, (int, float)):
        return str(v)
    return sql_str(v)

def random_date(start, end):
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta))

def iso_year_week(d):
    iso = d.isocalendar()
    return iso[0], iso[1]

# ---------------------------------------------------------------------------
# Buffers for batched INSERT statements
# ---------------------------------------------------------------------------
buffers = {}

def add_row(table, columns, values):
    buffers.setdefault(table, {"columns": columns, "rows": []})
    buffers[table]["rows"].append(values)

def emit_table(table, batch_size=500):
    if table not in buffers:
        return ""
    cols = buffers[table]["columns"]
    rows = buffers[table]["rows"]
    out = []
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES")
        line_parts = []
        for row in chunk:
            line_parts.append("  (" + ", ".join(sql_val(v) for v in row) + ")")
        out.append(",\n".join(line_parts) + ";")
    return "\n".join(out) + "\n\n"

# ---------------------------------------------------------------------------
# 1. Organisations
# ---------------------------------------------------------------------------
ORG_DEFS = [
    ("Northwind Analytics", "northwind-analytics", "retail", "north_america"),
    ("Helix Mobility", "helix-mobility", "automotive", "europe"),
    ("Cobalt Health Systems", "cobalt-health", "healthcare", "north_america"),
    ("Vantage Financial Group", "vantage-financial", "finance", "europe"),
    ("Orbital Logistics", "orbital-logistics", "logistics", "apac"),
]

orgs = []
for name, slug, vertical, region in ORG_DEFS:
    org_id = uid()
    created = random_date(START, START + timedelta(days=30))
    orgs.append({
        "id": org_id, "name": name, "slug": slug, "vertical": vertical,
        "region": region, "created_at": created,
    })
    add_row("organisations",
            ["id", "name", "slug", "vertical", "region", "is_active", "created_at", "updated_at"],
            [org_id, name, slug, vertical, region, True, created, TODAY])

# ---------------------------------------------------------------------------
# 2. Users (500) — roles & departments via full_name/email conventions
# ---------------------------------------------------------------------------
ROLES = ["client", "delivery_manager", "bsg_leadership", "super_admin"]
ROLE_WEIGHTS = [0.55, 0.30, 0.12, 0.03]
FIRST_NAMES = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Avery", "Quinn",
               "Drew", "Jamie", "Sam", "Reese", "Logan", "Parker", "Skyler", "Elena",
               "Marcus", "Priya", "Liu", "Fatima", "Diego", "Noor", "Ines", "Arben",
               "Vlora", "Besnik", "Mira", "Kushtrim", "Dafina", "Endrit"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
              "Davis", "Rodriguez", "Martinez", "Hashani", "Krasniqi", "Berisha",
              "Gashi", "Patel", "Chen", "Kovac", "Novak", "Ahmeti", "Zhu"]

users = []
for i in range(500):
    org = random.choice(orgs)
    role = random.choices(ROLES, weights=ROLE_WEIGHTS, k=1)[0]
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    user_id = uid()
    email = f"{first.lower()}.{last.lower()}.{i}@{org['slug']}.example.com"
    created = random_date(START, TODAY)
    is_active = random.random() > 0.05
    users.append({"id": user_id, "org_id": org["id"], "role": role, "created_at": created})
    add_row("users",
            ["id", "org_id", "email", "full_name", "role", "is_active", "created_at", "updated_at"],
            [user_id, org["id"], email, f"{first} {last}", role, is_active, created, TODAY])

users_by_org = {}
for u in users:
    users_by_org.setdefault(u["org_id"], []).append(u)

def pick_manager(org_id):
    candidates = [u for u in users_by_org.get(org_id, []) if u["role"] in ("delivery_manager", "bsg_leadership", "super_admin")]
    return random.choice(candidates) if candidates else random.choice(users)

# ---------------------------------------------------------------------------
# 3. Projects (50)
# ---------------------------------------------------------------------------
VERTICALS = ["computer_vision", "nlp_annotation", "content_moderation", "data_labeling", "speech_qa"]
PROJECT_STATUSES = ["active", "ramping", "paused", "completed", "cancelled"]
PROJECT_NOUNS = ["Vision QA", "Label Ops", "Content Shield", "Speech Audit", "Data Forge",
                  "Moderation Pulse", "Annotation Sprint", "Insight Pipeline", "Trust Layer",
                  "Signal Review"]

projects = []
for i in range(50):
    org = random.choice(orgs)
    pid = uid()
    start_date = random_date(START, TODAY - timedelta(days=60))
    duration = random.randint(90, 540)
    target_end = start_date + timedelta(days=duration)
    # status distribution: mix of healthy/at-risk/completed
    status = random.choices(PROJECT_STATUSES, weights=[0.40, 0.10, 0.08, 0.35, 0.07], k=1)[0]
    actual_end = None
    if status == "completed":
        actual_end = min(target_end + timedelta(days=random.randint(-15, 30)), TODAY)
    elif status == "cancelled":
        actual_end = random_date(start_date, min(target_end, TODAY))
    name = f"{org['name'].split()[0]} {random.choice(PROJECT_NOUNS)} {i+1}"
    health = random.choice(["healthy", "at_risk", "recovering", "declining"])
    projects.append({
        "id": pid, "org_id": org["id"], "name": name, "vertical": random.choice(VERTICALS),
        "status": status, "start_date": start_date, "target_end_date": target_end,
        "actual_end_date": actual_end, "health": health,
    })
    add_row("projects",
            ["id", "org_id", "name", "description", "vertical", "status", "start_date",
             "target_end_date", "actual_end_date", "daily_target_units", "created_at", "updated_at"],
            [pid, org["id"], name, f"Operational delivery engagement for {org['name']}.",
             projects[-1]["vertical"], status, start_date, target_end, actual_end,
             random.randint(200, 3000), start_date, TODAY])

active_projects = [p for p in projects if p["status"] in ("active", "ramping")]

# ---------------------------------------------------------------------------
# 4. Milestones (250, ~5 per project)
# ---------------------------------------------------------------------------
MILESTONE_STATUSES = ["pending", "on_track", "at_risk", "completed", "missed"]
milestones = []
for p in projects:
    n = 5
    span_days = max((p["target_end_date"] - p["start_date"]).days, 30)
    for m in range(n):
        mid = uid()
        planned = p["start_date"] + timedelta(days=int(span_days * (m + 1) / n))
        if planned > TODAY:
            status = random.choices(["pending", "on_track", "at_risk"], weights=[0.4, 0.4, 0.2], k=1)[0]
            actual = None
        else:
            status = random.choices(["completed", "missed", "at_risk"], weights=[0.7, 0.15, 0.15], k=1)[0]
            actual = planned + timedelta(days=random.randint(-5, 20)) if status == "completed" else None
        milestones.append({
            "id": mid, "project_id": p["id"], "org_id": p["org_id"],
            "planned_date": planned, "status": status,
        })
        add_row("milestones",
                ["id", "project_id", "org_id", "name", "description", "planned_date",
                 "actual_date", "status", "created_at", "updated_at"],
                [mid, p["id"], p["org_id"], f"Milestone {m+1}: {['Kickoff','Ramp','Mid-point Review','Stabilization','Closeout'][m]}",
                 "Auto-generated operational milestone.", planned, actual, status, p["start_date"], TODAY])

milestones_by_project = {}
for m in milestones:
    milestones_by_project.setdefault(m["project_id"], []).append(m)

# ---------------------------------------------------------------------------
# 5. Teams (per project) + Annotators (workforce assignments)
# ---------------------------------------------------------------------------
SITES = ["india", "kosovo"]
DOMAINS = ["computer_vision", "nlp", "content_review", "speech", "data_ops"]

teams = []
for p in projects:
    n_teams = random.randint(1, 3)
    for t in range(n_teams):
        tid = uid()
        site = random.choice(SITES)
        teams.append({"id": tid, "project_id": p["id"], "org_id": p["org_id"], "site": site})
        add_row("teams",
                ["id", "project_id", "org_id", "name", "site", "domain", "is_active", "created_at", "updated_at"],
                [tid, p["id"], p["org_id"], f"{p['name']} Team {t+1}", site, random.choice(DOMAINS),
                 True, p["start_date"], TODAY])

teams_by_project = {}
for t in teams:
    teams_by_project.setdefault(t["project_id"], []).append(t)

annotators = []
for t in teams:
    n_annot = random.randint(4, 12)
    for a in range(n_annot):
        aid = uid()
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        annotators.append({"id": aid, "org_id": t["org_id"], "team_id": t["id"]})
        add_row("annotators",
                ["id", "org_id", "team_id", "full_name", "site", "is_sme_certified", "is_active", "created_at", "updated_at"],
                [aid, t["org_id"], t["id"], f"{first} {last}", t["site"],
                 random.random() < 0.25, random.random() > 0.08, START, TODAY])

annotators_by_team = {}
for a in annotators:
    annotators_by_team.setdefault(a["team_id"], []).append(a)

# ---------------------------------------------------------------------------
# 6. Throughput snapshots ("tasks" equivalent — weekly units delivered)
#    Target ~2500 rows across 50 projects over ~2 years (biweekly cadence)
# ---------------------------------------------------------------------------
throughput_count = 0
for p in projects:
    cursor = p["start_date"]
    base = random.randint(150, 1200)
    trend = random.choice([1.0008, 1.0, 0.999, 1.0015, 0.9985])  # gentle improve/decline
    cur_level = base
    end_cap = min(p["actual_end_date"] or TODAY, TODAY)
    while cursor <= end_cap:
        cur_level = max(20, cur_level * trend + random.uniform(-15, 15))
        units = int(max(0, cur_level + random.uniform(-30, 30)))
        forecast = int(units * random.uniform(0.9, 1.1))
        rolling = int(units * random.uniform(0.85, 1.05))
        sid = uid()
        add_row("throughput_snapshots",
                ["id", "project_id", "org_id", "snapshot_date", "units_completed",
                 "units_forecast", "rolling_7day_units", "created_at", "updated_at"],
                [sid, p["id"], p["org_id"], cursor, units, forecast, rolling, cursor, cursor])
        throughput_count += 1
        cursor += timedelta(days=7)

# ---------------------------------------------------------------------------
# 7. Quality snapshots (target ~5000) + quality_error_entries (target ~10000)
# ---------------------------------------------------------------------------
ERROR_CATEGORIES = ["Boundary Error", "Missing Label", "Wrong Classification",
                     "False Positive", "False Negative", "Annotation Error"]
RECOMMENDED_ACTIONS = {
    "Boundary Error": "Recalibrate bounding-box tolerance guidelines and retrain on edge cases.",
    "Missing Label": "Add coverage checklist step and re-audit gold-set examples.",
    "Wrong Classification": "Schedule targeted taxonomy refresher training for affected reviewers.",
    "False Positive": "Tighten confidence threshold and add adjudication step.",
    "False Negative": "Expand gold-set sampling for rare classes and retrain detectors.",
    "Annotation Error": "Pair new annotators with SME for shadow review this cycle.",
}

quality_snapshots = []
quality_error_rows = 0
qs_target = 5000
qe_target = 10000

# Build candidate (project, team, week) combos across 2 years
combos = []
for p in projects:
    for t in teams_by_project.get(p["id"], []):
        cursor_week_start = p["start_date"]
        end_cap = min(p["actual_end_date"] or TODAY, TODAY)
        d = cursor_week_start
        while d <= end_cap:
            combos.append((p, t, d))
            d += timedelta(days=7)

random.shuffle(combos)
combos = combos[:qs_target]

# group combos by (project, team) to build a drifting quality trend over time
combos_by_pt = {}
for p, t, d in combos:
    combos_by_pt.setdefault((p["id"], t["id"]), []).append((p, t, d))
for key in combos_by_pt:
    combos_by_pt[key].sort(key=lambda x: x[2])

for (pid, tid), series in combos_by_pt.items():
    p, t, _ = series[0]
    base_acc = random.uniform(88, 97)
    trend = random.choice([0.04, -0.04, 0.0, 0.08, -0.08])  # pct improvement/decline per week
    level = base_acc
    for (proj, team, wdate) in series:
        level = min(99.5, max(70, level + trend + random.uniform(-1.5, 1.5)))
        iso_year, iso_week = iso_year_week(wdate)
        rework = max(0.5, min(35, 100 - level + random.uniform(-3, 3)))
        alpha = round(min(0.98, max(0.55, (level - 60) / 45 + random.uniform(-0.05, 0.05))), 3)
        has_drift = level < base_acc - 6 or rework > 20
        qsid = uid()
        quality_snapshots.append({
            "id": qsid, "project_id": proj["id"], "team_id": team["id"], "org_id": proj["org_id"],
            "iso_year": iso_year, "iso_week": iso_week, "week_date": wdate, "has_drift": has_drift,
        })
        add_row("quality_snapshots",
                ["id", "project_id", "team_id", "org_id", "iso_week", "iso_year",
                 "gold_set_accuracy_pct", "iaa_krippendorff_alpha", "rework_rate_pct",
                 "has_drift_alert", "drift_alert_detail", "created_at", "updated_at"],
                [qsid, proj["id"], team["id"], proj["org_id"], iso_week, iso_year,
                 sql_num(level), alpha, sql_num(rework), has_drift,
                 ("Accuracy trending below baseline for two consecutive weeks." if has_drift else None),
                 wdate, wdate])

        n_errors = random.randint(1, 4)
        cats = random.sample(ERROR_CATEGORIES, k=min(n_errors, len(ERROR_CATEGORIES)))
        remaining = 100.0
        for idx, cat in enumerate(cats):
            if idx == len(cats) - 1:
                share = round(remaining, 2)
            else:
                share = round(remaining * random.uniform(0.2, 0.6), 2)
                remaining -= share
            share = max(0.5, share)
            eid = uid()
            add_row("quality_error_entries",
                    ["id", "quality_snapshot_id", "org_id", "error_category", "share_pct",
                     "recommended_action", "created_at", "updated_at"],
                    [eid, qsid, proj["org_id"], cat, share, RECOMMENDED_ACTIONS[cat], wdate, wdate])
            quality_error_rows += 1

# top up error entries if under target by adding extra categories to random snapshots
qs_list_ids = [(qs["id"], qs["org_id"]) for qs in quality_snapshots]
while quality_error_rows < qe_target and qs_list_ids:
    qsid, org_id = random.choice(qs_list_ids)
    cat = random.choice(ERROR_CATEGORIES)
    eid = uid()
    add_row("quality_error_entries",
            ["id", "quality_snapshot_id", "org_id", "error_category", "share_pct",
             "recommended_action", "created_at", "updated_at"],
            [eid, qsid, org_id, cat, round(random.uniform(0.5, 15), 2), RECOMMENDED_ACTIONS[cat], TODAY, TODAY])
    quality_error_rows += 1

# ---------------------------------------------------------------------------
# 8. Risk alerts (delivery risk + quality drift = "drift alerts") & resolution
#    (resolution by delivery managers doubles as "governance actions")
# ---------------------------------------------------------------------------
ALERT_TYPES = ["delivery_risk", "quality_drift", "milestone_at_risk", "workforce_imbalance"]
RISK_TIERS = ["low", "medium", "high", "critical"]
ALERT_STATUSES = ["open", "acknowledged", "resolved", "dismissed"]

risk_alert_count = 0
for p in projects:
    n_alerts = random.randint(2, 8)
    proj_milestones = milestones_by_project.get(p["id"], [])
    for _ in range(n_alerts):
        atype = random.choice(ALERT_TYPES)
        tier = random.choices(RISK_TIERS, weights=[0.35, 0.35, 0.2, 0.1], k=1)[0]
        created = random_date(p["start_date"], min(p["actual_end_date"] or TODAY, TODAY))
        status = random.choices(ALERT_STATUSES, weights=[0.2, 0.2, 0.45, 0.15], k=1)[0]
        resolved_at = created + timedelta(days=random.randint(1, 21)) if status == "resolved" else None
        resolver = pick_manager(p["org_id"]) if status == "resolved" else None
        milestone_id = random.choice(proj_milestones)["id"] if proj_milestones and random.random() < 0.6 else None
        aid = uid()
        titles = {
            "delivery_risk": "Delivery timeline slippage risk detected",
            "quality_drift": "Quality drift detected against gold-set baseline",
            "milestone_at_risk": "Upcoming milestone trending at risk",
            "workforce_imbalance": "Workforce capacity imbalance across teams",
        }
        add_row("risk_alerts",
                ["id", "project_id", "org_id", "milestone_id", "alert_type", "risk_tier",
                 "title", "detail", "slippage_probability", "contributing_causes", "status",
                 "resolved_at", "resolved_by", "created_at", "updated_at"],
                [aid, p["id"], p["org_id"], milestone_id, atype, tier, titles[atype],
                 f"Automated detection flagged {atype.replace('_',' ')} for {p['name']}.",
                 round(random.uniform(0.05, 0.95), 3), None,
                 status, resolved_at, resolver["id"] if resolver else None, created, resolved_at or created])
        risk_alert_count += 1

# ---------------------------------------------------------------------------
# 9. Bottlenecks ("governance actions")
# ---------------------------------------------------------------------------
bottleneck_count = 0
for p in projects:
    if random.random() < 0.7:
        n = random.randint(1, 3)
        proj_teams = teams_by_project.get(p["id"], [])
        for _ in range(n):
            created = random_date(p["start_date"], min(p["actual_end_date"] or TODAY, TODAY))
            status = random.choices(ALERT_STATUSES, weights=[0.2, 0.2, 0.5, 0.1], k=1)[0]
            resolved_at = created + timedelta(days=random.randint(2, 30)) if status == "resolved" else None
            resolver = pick_manager(p["org_id"]) if status == "resolved" else None
            bid = uid()
            add_row("bottlenecks",
                    ["id", "project_id", "org_id", "team_id", "title", "detail", "status",
                     "resolved_at", "resolved_by", "created_at", "updated_at"],
                    [bid, p["id"], p["org_id"], (random.choice(proj_teams)["id"] if proj_teams else None),
                     "Reviewer capacity bottleneck identified",
                     f"Governance review flagged a capacity constraint for {p['name']}; escalation and remediation plan logged.",
                     status, resolved_at, resolver["id"] if resolver else None, created, resolved_at or created])
            bottleneck_count += 1

# ---------------------------------------------------------------------------
# 10. Client communications ("client updates") + evidence links
# ---------------------------------------------------------------------------
COMM_TYPES = ["weekly_summary", "executive_summary", "ad_hoc"]
COMM_STATUSES = ["draft", "in_review", "approved", "sent", "rejected"]

client_comm_count = 0
for p in projects:
    cursor = p["start_date"] + timedelta(days=7)
    end_cap = min(p["actual_end_date"] or TODAY, TODAY)
    while cursor <= end_cap:
        if random.random() < 0.5:  # ~biweekly cadence
            ctype = random.choices(COMM_TYPES, weights=[0.7, 0.2, 0.1], k=1)[0]
            status = random.choices(COMM_STATUSES, weights=[0.05, 0.05, 0.1, 0.75, 0.05], k=1)[0]
            reviewer = pick_manager(p["org_id"])
            approver = pick_manager(p["org_id"])
            reviewed_at = cursor + timedelta(hours=4) if status in ("in_review", "approved", "sent") else None
            approved_at = cursor + timedelta(hours=10) if status in ("approved", "sent") else None
            sent_at = cursor + timedelta(hours=14) if status == "sent" else None
            cid = uid()
            add_row("client_communications",
                    ["id", "project_id", "org_id", "comm_type", "subject", "body_draft",
                     "body_approved", "status", "drafted_by_agent", "reviewed_by", "reviewed_at",
                     "approved_by", "approved_at", "sent_at", "created_at", "updated_at"],
                    [cid, p["id"], p["org_id"], ctype, f"{p['name']} Status Update — {cursor.isoformat()}",
                     f"Draft summary of throughput, quality, and risk for {p['name']} as of {cursor.isoformat()}.",
                     (f"Approved summary of throughput, quality, and risk for {p['name']}." if status in ("approved", "sent") else None),
                     status, "ops-summary-agent", reviewer["id"], reviewed_at, approver["id"], approved_at, sent_at, cursor, cursor])
            client_comm_count += 1
        cursor += timedelta(days=14)

# ---------------------------------------------------------------------------
# 11. Client CSAT scores (monthly)
# ---------------------------------------------------------------------------
csat_count = 0
for p in projects:
    cursor = date(p["start_date"].year, p["start_date"].month, 1)
    end_cap = min(p["actual_end_date"] or TODAY, TODAY)
    client_users = [u for u in users_by_org.get(p["org_id"], []) if u["role"] == "client"]
    if not client_users:
        cursor = None
    while cursor and cursor <= end_cap:
        submitter = random.choice(client_users)
        score = round(min(5, max(1, random.gauss(4.0, 0.6))), 1)
        cid = uid()
        add_row("client_csat_scores",
                ["id", "project_id", "org_id", "submitted_by", "score", "reporting_period_month", "comment", "created_at"],
                [cid, p["id"], p["org_id"], submitter["id"], score, cursor,
                 "Generated quarterly satisfaction feedback." if random.random() < 0.3 else None, cursor])
        csat_count += 1
        nm = cursor.month + 1
        ny = cursor.year + (1 if nm > 12 else 0)
        nm = 1 if nm > 12 else nm
        cursor = date(ny, nm, 1)

# ---------------------------------------------------------------------------
# 12. Delivery confidence scores (per milestone)
# ---------------------------------------------------------------------------
dcs_count = 0
for m in milestones:
    p = next(pp for pp in projects if pp["id"] == m["project_id"])
    score = {"completed": random.uniform(85, 99), "on_track": random.uniform(70, 90),
              "pending": random.uniform(50, 80), "at_risk": random.uniform(30, 60),
              "missed": random.uniform(5, 35)}[m["status"]]
    forecast = m["planned_date"] + timedelta(days=random.randint(-10, 25))
    did = uid()
    add_row("delivery_confidence_scores",
            ["id", "project_id", "milestone_id", "org_id", "score_pct",
             "forecast_completion_date", "status", "model_version", "created_at"],
            [did, p["id"], m["id"], p["org_id"], sql_num(score), forecast, m["status"], "dcs-v1.3",
             m["planned_date"] - timedelta(days=5)])
    dcs_count += 1

# ---------------------------------------------------------------------------
# 13. Notifications
# ---------------------------------------------------------------------------
NOTIF_TYPES = ["risk_alert", "communication_pending", "milestone_at_risk", "quality_drift_detected", "system"]
notif_count = 0
managers = [u for u in users if u["role"] in ("delivery_manager", "bsg_leadership", "super_admin")]
for u in random.sample(managers, k=min(200, len(managers))):
    n = random.randint(1, 5)
    for _ in range(n):
        ntype = random.choice(NOTIF_TYPES)
        created = random_date(START, TODAY)
        nid = uid()
        is_read = random.random() < 0.6
        add_row("notifications",
                ["id", "user_id", "org_id", "notification_type", "title", "body", "source_table",
                 "source_row_id", "is_read", "sent_at", "created_at", "updated_at"],
                [nid, u["id"], u["org_id"], ntype, f"{ntype.replace('_',' ').title()} notice",
                 "Automated notification generated from operational monitoring.", None, None,
                 is_read, created, created, created])
        notif_count += 1

# ---------------------------------------------------------------------------
# 14. Agent queries (AI assistant usage log)
# ---------------------------------------------------------------------------
AGENT_NAMES = ["ops-copilot", "quality-analyst-agent", "risk-forecaster", "client-summary-agent"]
SAMPLE_QUERIES = [
    "What is the current delivery confidence for this project's next milestone?",
    "Summarize quality drift trends over the last 8 weeks.",
    "Which teams are contributing most to rework this month?",
    "Draft a client update covering throughput and risk status.",
]
agent_query_count = 0
for u in random.sample(users, k=min(150, len(users))):
    n = random.randint(1, 4)
    org_projects = [p for p in projects if p["org_id"] == u["org_id"]]
    for _ in range(n):
        proj = random.choice(org_projects) if org_projects and random.random() < 0.8 else None
        created = random_date(START, TODAY)
        qid = uid()
        q = random.choice(SAMPLE_QUERIES)
        add_row("agent_queries",
                ["id", "user_id", "org_id", "project_id", "agent_name", "query_text", "answer_text",
                 "model_used", "latency_ms", "created_at"],
                [qid, u["id"], u["org_id"], proj["id"] if proj else None, random.choice(AGENT_NAMES),
                 q, "Generated response summarizing the requested operational metrics.",
                 "claude-sonnet-4-6", random.randint(400, 4200), created])
        agent_query_count += 1

# ---------------------------------------------------------------------------
# Write seed.sql
# ---------------------------------------------------------------------------
TABLE_ORDER = [
    "organisations", "users", "projects", "milestones", "teams", "annotators",
    "throughput_snapshots", "quality_snapshots", "quality_error_entries",
    "risk_alerts", "bottlenecks", "client_communications", "client_csat_scores",
    "delivery_confidence_scores", "notifications", "agent_queries",
]

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write("-- Auto-generated operational seed data for the AI Operations Suite.\n")
    f.write("-- Generated by supabase/generate_seed.py — do not hand-edit; regenerate instead.\n")
    f.write("-- Covers ~2 years of synthetic history across organisations, projects, quality, and risk data.\n\n")
    f.write("BEGIN;\n\n")
    f.write("INSERT INTO metric_configurations (metric_key, display_label, is_client_visible, display_order, description)\n")
    f.write("VALUES\n")
    f.write("  ('delivery_confidence', 'Delivery Confidence', true, 1, 'Current schedule confidence for the active milestone.'),\n")
    f.write("  ('throughput_rolling_7d', '7-Day Throughput', true, 2, 'Rolling seven-day completed unit volume.'),\n")
    f.write("  ('gold_set_accuracy', 'Gold-Set Accuracy', true, 3, 'Weekly quality accuracy against gold-set labels.'),\n")
    f.write("  ('rework_rate', 'Rework Rate', true, 4, 'Weekly percentage of work requiring rework.')\n")
    f.write("ON CONFLICT (metric_key) DO UPDATE SET\n")
    f.write("  display_label = EXCLUDED.display_label,\n")
    f.write("  is_client_visible = EXCLUDED.is_client_visible,\n")
    f.write("  display_order = EXCLUDED.display_order,\n")
    f.write("  description = EXCLUDED.description;\n\n")

    for table in TABLE_ORDER:
        f.write(f"-- {table}\n")
        f.write(emit_table(table))

    f.write("COMMIT;\n")

print("organisations:", len(orgs))
print("users:", len(users))
print("projects:", len(projects))
print("milestones:", len(milestones))
print("teams:", len(teams))
print("annotators:", len(annotators))
print("throughput_snapshots:", throughput_count)
print("quality_snapshots:", len(quality_snapshots))
print("quality_error_entries:", quality_error_rows)
print("risk_alerts:", risk_alert_count)
print("bottlenecks:", bottleneck_count)
print("client_communications:", client_comm_count)
print("client_csat_scores:", csat_count)
print("delivery_confidence_scores:", dcs_count)
print("notifications:", notif_count)
print("agent_queries:", agent_query_count)
print(f"Wrote {OUT_PATH}")
print("Load into Supabase with: python apply_seed.py")

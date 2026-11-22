import os
import json
import datetime
import threading
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
_run_lock = threading.Lock()          # only one agent run at a time

STATUS_ORDER = ["Excellent", "Good", "Warning", "Critical"]
SEVERITY_SORT = ("CASE {c} WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                 "WHEN 'medium' THEN 2 ELSE 3 END")


# ---------------------------------------------------------------- helpers
def _default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime.datetime):
        return o.strftime("%Y-%m-%d %H:%M")
    if isinstance(o, datetime.date):
        return o.isoformat()
    return str(o)


def clean(obj):
    return json.loads(json.dumps(obj, default=_default))


def q(sql, **params):
    return pd.read_sql(text(sql), engine, params=params or None)


def records(df):
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            valid = df[c].dropna()
            fmt = "%Y-%m-%d" if (valid.dt.normalize() == valid).all() else "%Y-%m-%d %H:%M"
            df[c] = df[c].dt.strftime(fmt)
    df = df.astype(object).where(df.notna(), None)
    return clean(df.to_dict("records"))


def exists(table):
    return not q("SELECT 1 FROM information_schema.tables "
                 "WHERE table_schema = 'public' AND table_name = :t", t=table).empty


def need(*tables):
    missing = [t for t in tables if not exists(t)]
    if missing:
        raise HTTPException(
            status_code=409,
            detail="Missing table(s): " + ", ".join(missing)
                   + ". Run python maintenance_agent.py first.")


def check_facility(facility_id):
    if facility_id is None:
        return
    if q("SELECT 1 FROM facilities WHERE facility_id = :f", f=facility_id).empty:
        raise HTTPException(status_code=404, detail=f"Facility {facility_id} not found")


def facility_filter(facility_id, column):
    if facility_id is None:
        return "", {}
    return f" AND {column} = :f", {"f": facility_id}


def num(value):
    return 0.0 if value is None or pd.isna(value) else float(value)


# ---------------------------------------------------------------- summary
@router.get("/summary")
def summary(facility_id: Optional[int] = None):
    need("assets", "asset_health", "failure_predictions")
    check_facility(facility_id)
    fa, p = facility_filter(facility_id, "facility_id")
    fa_a, _ = facility_filter(facility_id, "a.facility_id")

    assets_monitored = int(q(f"SELECT COUNT(*) AS n FROM assets WHERE 1=1{fa}", **p).n[0])
    avg_health = num(q(f"SELECT AVG(health_score) AS v FROM asset_health WHERE 1=1{fa}", **p).v[0])
    h = q(f"SELECT status, COUNT(*) AS machines FROM asset_health WHERE 1=1{fa} GROUP BY status", **p)
    counts = dict(zip(h.status, h.machines))
    total = sum(counts.values())
    distribution = [dict(status=s, machines=int(counts.get(s, 0)),
                         percent=round(100 * counts.get(s, 0) / total, 1) if total else 0)
                    for s in STATUS_ORDER]
    predicted = int(q(f"SELECT COUNT(*) AS n FROM failure_predictions "
                      f"WHERE will_fail_14d{fa}", **p).n[0])
    overdue = int(q(f"SELECT COUNT(*) AS n FROM asset_health "
                    f"WHERE days_overdue > 0{fa}", **p).n[0])
    as_of = q("SELECT MAX(predicted_at) AS t FROM failure_predictions").t[0]

    open_orders = 0
    if exists("work_orders"):
        open_orders = int(q("SELECT COUNT(*) AS n FROM work_orders w "
                            "JOIN assets a ON a.asset_id = w.asset_id "
                            f"WHERE w.status = 'open'{fa_a}", **p).n[0])
    open_alerts = critical_alerts = 0
    if exists("alerts"):
        a = q("SELECT severity, COUNT(*) AS n FROM alerts "
              f"WHERE status = 'open' AND source = 'Maintenance Agent'{fa} "
              "GROUP BY severity", **p)
        open_alerts = int(a.n.sum()) if len(a) else 0
        critical_alerts = int(a[a.severity == "critical"].n.sum()) if len(a) else 0
    ongoing = 0
    if exists("equipment_events"):
        ongoing = int(q("SELECT COUNT(*) AS n FROM equipment_events e "
                        "JOIN assets a ON a.asset_id = e.asset_id "
                        f"WHERE e.event_type = 'Ongoing'{fa_a}", **p).n[0])
    saving = downtime = 0.0
    jobs = 0
    if exists("maintenance_schedule"):
        s = q("SELECT COALESCE(SUM(potential_saving_rs), 0) AS s, "
              "COALESCE(SUM(downtime_avoided_hours), 0) AS d, COUNT(*) AS jobs "
              f"FROM maintenance_schedule WHERE 1=1{fa}", **p)
        saving, downtime, jobs = num(s.s[0]), num(s.d[0]), int(s.jobs[0])

    return clean(dict(
        facility_id=facility_id, as_of=None if pd.isna(as_of) else as_of,
        kpis=dict(assets_monitored=assets_monitored, avg_health=round(avg_health, 1),
                  predicted_failures=predicted, open_work_orders=open_orders,
                  open_alerts=open_alerts, critical_alerts=critical_alerts,
                  ongoing_events=ongoing, overdue_services=overdue,
                  scheduled_jobs=jobs, potential_saving_rs=round(saving),
                  downtime_avoided_hours=round(downtime, 1)),
        distribution=distribution))


# ---------------------------------------------------------------- assets
@router.get("/assets")
def assets(facility_id: Optional[int] = None,
           status: Optional[str] = Query(None, pattern="^(Excellent|Good|Warning|Critical)$"),
           limit: int = Query(200, ge=1, le=500)):
    need("asset_health", "failure_predictions")
    check_facility(facility_id)
    fa, p = facility_filter(facility_id, "h.facility_id")
    st = ""
    if status:
        st, p["st"] = " AND h.status = :st", status
    df = q("SELECT h.asset_id, h.asset_name, h.asset_type, h.facility_id, h.criticality, "
           "h.health_score, h.status, h.life_used_pct, h.days_overdue, h.main_issue, "
           "p.risk_pct, p.risk_level "
           "FROM asset_health h LEFT JOIN failure_predictions p ON p.asset_id = h.asset_id "
           f"WHERE 1=1{fa}{st} ORDER BY h.health_score ASC, h.asset_id LIMIT :lim",
           lim=limit, **p)
    return clean(dict(total=len(df), items=records(df)))


@router.get("/health-by-type")
def health_by_type(facility_id: Optional[int] = None):
    need("asset_health")
    check_facility(facility_id)
    fa, p = facility_filter(facility_id, "facility_id")
    df = q("SELECT asset_type, COUNT(*) AS machines, ROUND(AVG(health_score), 1) AS avg_health, "
           "SUM(CASE WHEN status IN ('Warning', 'Critical') THEN 1 ELSE 0 END) AS at_risk "
           f"FROM asset_health WHERE 1=1{fa} GROUP BY asset_type ORDER BY avg_health ASC", **p)
    return clean(dict(items=records(df)))


@router.get("/events")
def events(facility_id: Optional[int] = None,
           event_type: Optional[str] = Query(None, pattern="^(Ongoing|Breakdown|Transient)$"),
           limit: int = Query(50, ge=1, le=500)):
    need("equipment_events")
    check_facility(facility_id)
    fa, p = facility_filter(facility_id, "a.facility_id")
    et = ""
    if event_type:
        et, p["et"] = " AND e.event_type = :et", event_type
    df = q("SELECT e.event_id, e.asset_id, a.asset_name, a.asset_type, a.facility_id, "
           "e.start_time, e.end_time, e.duration_hours, e.peak_score, e.severity, "
           "e.main_channel, e.event_type, e.message "
           "FROM equipment_events e JOIN assets a ON a.asset_id = e.asset_id "
           f"WHERE 1=1{fa}{et} ORDER BY e.start_time DESC LIMIT :lim", lim=limit, **p)
    return clean(dict(total=len(df), items=records(df)))


# ---------------------------------------------------------------- predictions
@router.get("/predictions")
def predictions(facility_id: Optional[int] = None, only_flagged: bool = False,
                limit: int = Query(100, ge=1, le=500)):
    need("failure_predictions", "asset_health")
    check_facility(facility_id)
    fa, p = facility_filter(facility_id, "p.facility_id")
    flag = " AND p.will_fail_14d" if only_flagged else ""
    df = q("SELECT p.asset_id, p.asset_name, p.asset_type, p.facility_id, p.criticality, "
           "p.risk_pct, p.risk_level, p.will_fail_14d, p.reason, p.horizon_days, "
           "p.predicted_at, h.health_score "
           "FROM failure_predictions p LEFT JOIN asset_health h ON h.asset_id = p.asset_id "
           f"WHERE 1=1{fa}{flag} ORDER BY p.risk_pct DESC, p.asset_id LIMIT :lim",
           lim=limit, **p)
    return clean(dict(total=len(df), items=records(df)))


@router.get("/model-metrics")
def model_metrics():
    need("failure_model_metrics")
    df = q("SELECT * FROM failure_model_metrics ORDER BY metrics_id DESC LIMIT 1")
    if df.empty:
        raise HTTPException(status_code=404,
                            detail="No model metrics yet. Run python predict.py first.")
    return records(df)[0]


# ---------------------------------------------------------------- schedule
@router.get("/schedule")
def schedule(facility_id: Optional[int] = None,
             label: Optional[str] = Query(None, pattern="^(Emergency|Urgent|Planned|Routine)$")):
    need("maintenance_schedule")
    check_facility(facility_id)
    fa, p = facility_filter(facility_id, "s.facility_id")
    lab = ""
    if label:
        lab, p["lab"] = " AND s.priority_label = :lab", label
    df = q("SELECT s.schedule_id, s.asset_id, s.asset_name, s.asset_type, s.facility_id, "
           "s.criticality, s.priority_label, s.priority_score, s.risk_pct, s.health_score, "
           "s.task, s.reason, s.recommended_date, s.due_by, s.existing_booking, s.note, "
           "s.potential_saving_rs, s.downtime_avoided_hours "
           f"FROM maintenance_schedule s WHERE 1=1{fa}{lab} "
           "ORDER BY s.recommended_date, CASE s.priority_label WHEN 'Emergency' THEN 0 "
           "WHEN 'Urgent' THEN 1 WHEN 'Planned' THEN 2 ELSE 3 END, s.priority_score DESC", **p)
    items = records(df)
    per_day = []
    for day, g in df.groupby("recommended_date"):
        per_day.append(dict(date=str(day)[:10], jobs=int(len(g)),
                            emergency=int((g.priority_label == "Emergency").sum())))
    totals = dict(jobs=len(df),
                  emergency=int((df.priority_label == "Emergency").sum()),
                  potential_saving_rs=round(num(df.potential_saving_rs.astype(float).sum())),
                  downtime_avoided_hours=round(num(df.downtime_avoided_hours.astype(float).sum()), 1))
    return clean(dict(items=items, per_day=per_day, totals=totals))


# ---------------------------------------------------------------- alerts and work orders
@router.get("/alerts")
def alerts(facility_id: Optional[int] = None,
           severity: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
           status: Optional[str] = Query(None, pattern="^(open|acknowledged|closed)$")):
    need("alerts")
    check_facility(facility_id)
    fa, p = facility_filter(facility_id, "al.facility_id")
    extra = ""
    if severity:
        extra += " AND al.severity = :sev"
        p["sev"] = severity
    if status:
        extra += " AND al.status = :stt"
        p["stt"] = status
    df = q("SELECT al.alert_id, al.facility_id, al.asset_id, a.asset_name, a.asset_type, "
           "al.alert_type, al.severity, al.title, al.message, al.notify, al.status, al.created_at "
           "FROM alerts al LEFT JOIN assets a ON a.asset_id = al.asset_id "
           f"WHERE al.source = 'Maintenance Agent'{fa}{extra} "
           f"ORDER BY {SEVERITY_SORT.format(c='al.severity')}, al.alert_id", **p)
    return clean(dict(total=len(df), items=records(df)))


@router.get("/work-orders")
def work_orders(facility_id: Optional[int] = None,
                priority: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
                status: Optional[str] = Query(None, pattern="^(open|in_progress|done)$"),
                limit: int = Query(200, ge=1, le=1000)):
    need("work_orders")
    check_facility(facility_id)
    fa, p = facility_filter(facility_id, "a.facility_id")
    extra = ""
    if priority:
        extra += " AND w.priority = :pri"
        p["pri"] = priority
    if status:
        extra += " AND w.status = :stt"
        p["stt"] = status
    df = q("SELECT w.work_id, w.asset_id, a.asset_name, a.asset_type, a.facility_id, "
           "w.priority, w.title, w.description, w.due_date, w.status, w.source, w.created_at "
           "FROM work_orders w JOIN assets a ON a.asset_id = w.asset_id "
           f"WHERE 1=1{fa}{extra} "
           f"ORDER BY w.due_date, {SEVERITY_SORT.format(c='w.priority')}, w.work_id LIMIT :lim",
           lim=limit, **p)
    return clean(dict(total=len(df), items=records(df)))


# ---------------------------------------------------------------- the agent
@router.get("/agent/last-run")
def last_run():
    if not exists("agent_runs"):
        return {"run": None}
    df = q("SELECT run_id, finished_at, source, jobs, alerts, emergencies, summary, steps "
           "FROM agent_runs WHERE agent = 'Maintenance Agent' "
           "ORDER BY run_id DESC LIMIT 1")
    if df.empty:
        return {"run": None}
    run = records(df)[0]
    run["steps"] = json.loads(run["steps"]) if run.get("steps") else []
    return {"run": run}


@router.post("/agent/run")
def run_agent():
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="The Maintenance Agent is already running. Please wait.")
    try:
        from maintenance_agent import run_maintenance_agent
        out = run_maintenance_agent(save=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"The agent failed: {e}")
    finally:
        _run_lock.release()
    return clean(dict(
        steps=out["steps"], issues=out["issues"], source=out["source"],
        summary=out["summary"], jobs=len(out["jobs"]), alerts=len(out["alerts"]),
        emergencies=sum(1 for j in out["jobs"] if j["priority"] == "Emergency")))
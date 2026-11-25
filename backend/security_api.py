"""
security_api.py  (Milestone 3 - Step 6)
9 read-only endpoints for the Security dashboard.
"""
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from api_utils import (FACILITIES, check_facility, clean, need_tables, q, sort_by_severity, table_exists)

router = APIRouter(prefix="/api/security", tags=["security"])
SEVERITIES = ["Critical", "High", "Medium", "Low"]


@router.get("/summary")
def summary(facility_id: int):
    check_facility(facility_id)
    need_tables("security_events", "access_logs", "cctv_events", "visitors", "security_eval_metrics")
    ev = q("SELECT severity, timestamp FROM security_events WHERE facility_id = :f", f=facility_id)
    by_sev = {s: int((ev["severity"] == s).sum()) for s in SEVERITIES}
    acc = q("SELECT COUNT(*) AS swipes, SUM(CASE WHEN result = 'DENIED' THEN 1 ELSE 0 END) AS denied "
            "FROM access_logs WHERE facility_id = :f", f=facility_id).iloc[0]
    cctv = int(q("SELECT COUNT(*) AS n FROM cctv_events WHERE facility_id = :f", f=facility_id)["n"].iloc[0])
    vis = int(q("SELECT COUNT(*) AS n FROM visitors WHERE facility_id = :f", f=facility_id)["n"].iloc[0])
    open_alerts = {}
    if table_exists("security_alerts"):
        a = q("SELECT severity, COUNT(*) AS n FROM security_alerts WHERE facility_id = :f AND status = 'open' "
              "GROUP BY severity", f=facility_id)
        open_alerts = {r.severity: int(r.n) for r in a.itertuples()}
    det = q("SELECT * FROM security_eval_metrics WHERE event_type = 'ALL'")
    last = pd.to_datetime(ev["timestamp"]).max() if len(ev) else None
    return {
        "events_total": int(len(ev)), "events_by_severity": by_sev,
        "last_event": None if last is None else last.strftime("%Y-%m-%d %H:%M"),
        "badge_swipes": int(acc["swipes"]), "denied_swipes": int(acc["denied"] or 0),
        "denied_rate_pct": round(float(acc["denied"] or 0) / max(int(acc["swipes"]), 1) * 100, 2),
        "cctv_events": cctv, "visitors": vis,
        "open_alerts": open_alerts, "open_alerts_total": int(sum(open_alerts.values())),
        "detection": clean(det)[0] if len(det) else None,
    }


@router.get("/events")
def events(facility_id: int, severity: Optional[str] = None, event_type: Optional[str] = None,
           limit: int = Query(100, ge=1, le=500)):
    check_facility(facility_id)
    need_tables("security_events")
    d = q("SELECT * FROM security_events WHERE facility_id = :f", f=facility_id)
    if severity:
        d = d[d["severity"] == severity]
    if event_type:
        d = d[d["event_type"] == event_type]
    d = d.assign(_t=pd.to_datetime(d["timestamp"])).sort_values("_t", ascending=False).drop(columns="_t").head(limit)
    return clean(d, time_cols=("timestamp",))


@router.get("/event-types")
def event_types(facility_id: int):
    check_facility(facility_id)
    need_tables("security_events")
    d = q("SELECT event_type, severity FROM security_events WHERE facility_id = :f", f=facility_id)
    if d.empty:
        return []
    g = d.groupby("event_type").agg(count=("severity", "size"), severity=("severity", "first")).reset_index()
    return clean(g.sort_values("count", ascending=False))


@router.get("/timeline")
def timeline(facility_id: int):
    check_facility(facility_id)
    need_tables("security_events")
    d = q("SELECT timestamp, severity FROM security_events WHERE facility_id = :f", f=facility_id)
    if d.empty:
        return []
    d["date"] = pd.to_datetime(d["timestamp"]).dt.strftime("%Y-%m-%d")
    g = d.groupby("date").agg(count=("severity", "size"),
                              critical=("severity", lambda s: int((s == "Critical").sum()))).reset_index()
    return clean(g.sort_values("date"))


@router.get("/alerts")
def alerts(facility_id: int, severity: Optional[str] = None):
    check_facility(facility_id)
    if not table_exists("security_alerts"):
        return []                      # the agent has not been run yet
    d = q("SELECT * FROM security_alerts WHERE facility_id = :f", f=facility_id)
    if severity:
        d = d[d["severity"] == severity]
    d = sort_by_severity(d, "event_time")
    return clean(d.drop(columns=["dedupe_key"], errors="ignore"), time_cols=("event_time", "created_at"))


@router.get("/visitors")
def visitors(facility_id: int, limit: int = Query(50, ge=1, le=500)):
    check_facility(facility_id)
    need_tables("visitors", "occupancy_zones")
    v = q("SELECT visitor_id, check_in, check_out, zone_visited, purpose FROM visitors WHERE facility_id = :f",
          f=facility_id)
    zr = q("SELECT zone, restricted FROM occupancy_zones WHERE facility_id = :f", f=facility_id)
    restricted = set(zr[zr["restricted"].astype(bool)]["zone"])
    v["check_in"] = pd.to_datetime(v["check_in"])
    v["check_out"] = pd.to_datetime(v["check_out"])
    v["stay_hours"] = ((v["check_out"] - v["check_in"]).dt.total_seconds() / 3600).round(1)

    def flag(r):
        if pd.isna(r["check_out"]):
            return "No check-out"
        if r["zone_visited"] in restricted:
            return "Restricted zone"
        if r["stay_hours"] > 10:
            return "Overstay"
        return "Normal"

    v["flag"] = v.apply(flag, axis=1)
    counts = v["flag"].value_counts().to_dict()
    recent = v.sort_values("check_in", ascending=False).head(limit)
    return {"total": int(len(v)), "flagged": int((v["flag"] != "Normal").sum()),
            "by_flag": {k: int(n) for k, n in counts.items()},
            "avg_stay_hours": round(float(v["stay_hours"].mean()), 1),
            "recent": clean(recent, time_cols=("check_in", "check_out"))}


@router.get("/access-stats")
def access_stats(facility_id: int):
    check_facility(facility_id)
    need_tables("access_logs")
    d = q("SELECT zone, COUNT(*) AS swipes, SUM(CASE WHEN result = 'DENIED' THEN 1 ELSE 0 END) AS denied "
          "FROM access_logs WHERE facility_id = :f GROUP BY zone ORDER BY swipes DESC", f=facility_id)
    d["denied"] = d["denied"].fillna(0).astype(int)
    d["denied_rate_pct"] = (d["denied"] / d["swipes"] * 100).round(2)
    return clean(d)


@router.get("/investigate/{event_id}")
def investigate(event_id: int):
    """Everything we know around one security event, to help an investigation."""
    need_tables("security_events", "access_logs", "cctv_events")
    e = q("SELECT * FROM security_events WHERE event_id = :i", i=event_id)
    if e.empty:
        raise HTTPException(404, f"No security event {event_id}")
    ev = e.iloc[0]
    t = pd.to_datetime(ev["timestamp"])
    out = {"event": clean(e, time_cols=("timestamp",))[0], "badge_timeline": [], "door_swipes": [],
           "cctv_nearby": [], "alert": None}
    cols = "timestamp, zone, direction, result, badge_id"
    if ev["badge_id"] is not None and pd.notna(ev["badge_id"]):
        a = q(f"SELECT facility_id, {cols} FROM access_logs WHERE badge_id = :b", b=ev["badge_id"])
        a["timestamp"] = pd.to_datetime(a["timestamp"])
        a = a[(a["timestamp"] - t).abs() <= pd.Timedelta(hours=3)].sort_values("timestamp")
        out["badge_timeline"] = clean(a, time_cols=("timestamp",))
    if ev["zone"] is not None and pd.notna(ev["zone"]):
        d = q(f"SELECT {cols} FROM access_logs WHERE facility_id = :f AND zone = :z",
              f=int(ev["facility_id"]), z=ev["zone"])
        d["timestamp"] = pd.to_datetime(d["timestamp"])
        d = d[(d["timestamp"] - t).abs() <= pd.Timedelta(minutes=10)].sort_values("timestamp")
        out["door_swipes"] = clean(d.head(20), time_cols=("timestamp",))
        c = q("SELECT timestamp, zone, event_type, persons_detected, duration_min FROM cctv_events "
              "WHERE facility_id = :f AND zone = :z", f=int(ev["facility_id"]), z=ev["zone"])
        c["timestamp"] = pd.to_datetime(c["timestamp"])
        c = c[(c["timestamp"] - t).abs() <= pd.Timedelta(minutes=30)].sort_values("timestamp")
        out["cctv_nearby"] = clean(c.head(20), time_cols=("timestamp",))
    if table_exists("security_alerts"):
        al = q("SELECT message, recommended_action, escalate_to, evidence, severity FROM security_alerts "
               "WHERE facility_id = :f AND alert_type = :t AND event_time = :ts",
               f=int(ev["facility_id"]), t=ev["event_type"], ts=t.to_pydatetime())
        if len(al):
            out["alert"] = clean(al)[0]
    return out


@router.get("/evaluation")
def evaluation():
    need_tables("security_eval_metrics", "security_ml_check")
    return {"rules": clean(q("SELECT * FROM security_eval_metrics")),
            "ml": clean(q("SELECT * FROM security_ml_check"))}
"""
occupancy_api.py  (Milestone 3 - Step 6)
9 read-only endpoints for the Occupancy dashboard. Data comes from the tables
created in Steps 1-5, so every call is fast.
"""
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from api_utils import (FACILITIES, check_facility, clean, need_tables, q, sort_by_severity, table_exists)

router = APIRouter(prefix="/api/occupancy", tags=["occupancy"])


@router.get("/facilities")
def facilities():
    return [{"facility_id": k, "name": v} for k, v in FACILITIES.items()]


@router.get("/summary")
def summary(facility_id: int):
    check_facility(facility_id)
    need_tables("occupancy_facility_summary", "occupancy_eval_metrics", "occupancy_forecast_metrics")
    f = q("SELECT * FROM occupancy_facility_summary WHERE facility_id = :f", f=facility_id)
    if f.empty:
        raise HTTPException(404, "No summary for this facility. Run occupancy.py")
    open_alerts = {}
    if table_exists("occupancy_alerts"):
        a = q("SELECT severity, COUNT(*) AS n FROM occupancy_alerts WHERE facility_id = :f AND status = 'open' "
              "GROUP BY severity", f=facility_id)
        open_alerts = {r.severity: int(r.n) for r in a.itertuples()}
    fm = q("SELECT model, accuracy_pct, mae_people, within_10pct_capacity FROM occupancy_forecast_metrics")
    det = q("SELECT * FROM occupancy_eval_metrics WHERE threshold_pct = 100")
    return {
        "facility": clean(f)[0],
        "open_alerts": open_alerts,
        "open_alerts_total": int(sum(open_alerts.values())),
        "forecast_models": clean(fm),
        "forecast_target_pct": 80,
        "detection": clean(det)[0] if len(det) else None,
    }


@router.get("/zones")
def zones(facility_id: int):
    check_facility(facility_id)
    need_tables("occupancy_zone_summary")
    z = q("SELECT * FROM occupancy_zone_summary WHERE facility_id = :f ORDER BY zone", f=facility_id)
    return clean(z)


@router.get("/current")
def current(facility_id: int):
    """Latest hour in the data: how full is each zone right now (as of the end of the data)."""
    check_facility(facility_id)
    need_tables("occupancy_records", "occupancy_zones")
    d = q("SELECT r.zone, r.occupancy_count, r.timestamp, z.capacity, z.zone_type, z.restricted "
          "FROM occupancy_records r JOIN occupancy_zones z "
          "ON z.facility_id = r.facility_id AND z.zone = r.zone "
          "WHERE r.facility_id = :f AND r.timestamp = "
          "(SELECT MAX(timestamp) FROM occupancy_records WHERE facility_id = :f) ORDER BY r.zone", f=facility_id)
    d["utilization"] = (d["occupancy_count"] / d["capacity"] * 100).round(1)
    d["status"] = d["utilization"].apply(lambda u: "Over capacity" if u > 100 else "Near full" if u >= 90 else "Normal")
    as_of = pd.to_datetime(d["timestamp"]).max() if len(d) else None
    return {"as_of": None if as_of is None else as_of.strftime("%Y-%m-%d %H:%M"),
            "zones": clean(d.drop(columns=["timestamp"]))}


@router.get("/heatmap")
def heatmap(facility_id: int, day_type: str = Query("Weekday")):
    check_facility(facility_id)
    if day_type not in ("Weekday", "Weekend"):
        raise HTTPException(400, "day_type must be Weekday or Weekend")
    need_tables("occupancy_heatmap")
    h = q("SELECT zone, hour, avg_utilization FROM occupancy_heatmap WHERE facility_id = :f AND day_type = :d",
          f=facility_id, d=day_type)
    pv = h.pivot(index="zone", columns="hour", values="avg_utilization").reindex(columns=range(24)).fillna(0)
    return {"day_type": day_type, "hours": list(range(24)), "zones": list(pv.index),
            "values": [[float(v) for v in row] for row in pv.to_numpy()]}


@router.get("/incidents")
def incidents(facility_id: int, limit: int = Query(50, ge=1, le=500)):
    check_facility(facility_id)
    need_tables("occupancy_incidents")
    d = q("SELECT * FROM occupancy_incidents WHERE facility_id = :f ORDER BY start_time DESC LIMIT :n",
          f=facility_id, n=limit)
    return clean(d, time_cols=("start_time", "end_time"))


@router.get("/forecast")
def forecast(facility_id: int, zone: str):
    check_facility(facility_id)
    need_tables("occupancy_forecast", "occupancy_records")
    fc = q("SELECT timestamp, predicted_count, predicted_utilization, risk, capacity FROM occupancy_forecast "
           "WHERE facility_id = :f AND zone = :z ORDER BY timestamp", f=facility_id, z=zone)
    if fc.empty:
        raise HTTPException(404, f"No forecast for zone '{zone}'")
    act = q("SELECT timestamp, occupancy_count FROM occupancy_records WHERE facility_id = :f AND zone = :z "
            "ORDER BY timestamp DESC LIMIT 168", f=facility_id, z=zone).iloc[::-1]
    return {"zone": zone, "capacity": int(fc["capacity"].iloc[0]),
            "actual": clean(act, time_cols=("timestamp",)),
            "forecast": clean(fc.drop(columns=["capacity"]), time_cols=("timestamp",))}


@router.get("/forecast-metrics")
def forecast_metrics(facility_id: Optional[int] = None):
    need_tables("occupancy_forecast_metrics", "occupancy_forecast_zone_metrics")
    m = q("SELECT * FROM occupancy_forecast_metrics")
    if facility_id is None:
        z = q("SELECT * FROM occupancy_forecast_zone_metrics ORDER BY facility_id, zone")
    else:
        check_facility(facility_id)
        z = q("SELECT * FROM occupancy_forecast_zone_metrics WHERE facility_id = :f ORDER BY zone", f=facility_id)
    return {"target_pct": 80, "models": clean(m), "zones": clean(z)}


@router.get("/alerts")
def alerts(facility_id: int, severity: Optional[str] = None):
    check_facility(facility_id)
    if not table_exists("occupancy_alerts"):
        return []                      # the agent has not been run yet
    d = q("SELECT * FROM occupancy_alerts WHERE facility_id = :f", f=facility_id)
    if severity:
        d = d[d["severity"] == severity]
    d = sort_by_severity(d, "event_time")
    return clean(d.drop(columns=["dedupe_key"], errors="ignore"), time_cols=("event_time", "created_at"))
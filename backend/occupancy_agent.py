"""
occupancy_agent.py  (Milestone 3 - Step 5)
Occupancy Agent built with LangGraph. Steps (nodes):
  load_data -> validate_data -> analyze -> select_recent -> forecast_risk
            -> build_alerts -> reword -> save          (stops early if the data is bad)

Run:  python occupancy_agent.py --dry-run     (shows alerts, saves nothing)
      python occupancy_agent.py               (saves to occupancy_alerts + m3_agent_runs)
      python occupancy_agent.py --days 30     (look back 30 days from the end of the data)
"""
import argparse
from datetime import datetime
from typing import Any, TypedDict

import pandas as pd
from langgraph.graph import END, START, StateGraph
from sqlalchemy import inspect

import occupancy as occ_mod
from agent_common import (SAVE_COLS, SEVERITY_RANK, get_engine, llm_reword, log_run, new_run_id, save_alerts)

TABLE = "occupancy_alerts"
ACTIONS = {
    "cafeteria": "Stagger lunch times or open overflow seating.",
    "meeting": "Move teams to free rooms and review room booking limits.",
    "training": "Split the session or move part of it to a bigger room.",
    "clinic": "Open another registration counter and guide patients to waiting areas.",
    "emergency": "Alert the duty manager and prepare overflow bays.",
    "pharmacy": "Open an extra counter and manage the queue.",
}
DEFAULT_ACTION = "Check the zone and guide people to less crowded areas."


class State(TypedDict, total=False):
    dry_run: bool
    days: int
    run_id: str
    started: Any
    occ: Any
    zones: Any
    forecast: Any
    problems: list
    stop: bool
    df: Any
    zsum: Any
    incidents: Any
    data_end: Any
    recent: Any
    underused: Any
    near_full: Any
    alerts: list
    used_llm: bool
    created: int
    skipped: int


# ------------------------------------------------------------------ nodes
def load_data(s: State):
    engine = get_engine()
    occ, zones = occ_mod.load(engine)
    fc = pd.DataFrame()
    if inspect(engine).has_table("occupancy_forecast"):
        fc = pd.read_sql("SELECT facility_id, zone, timestamp, predicted_utilization, risk FROM occupancy_forecast", engine)
        fc["timestamp"] = pd.to_datetime(fc["timestamp"]).astype("datetime64[ns]")
    return {"occ": occ, "zones": zones, "forecast": fc}


def validate_data(s: State):
    problems = occ_mod.validate(s["occ"], s["zones"])
    return {"problems": problems, "stop": bool(problems)}


def analyze(s: State):
    df = occ_mod.prepare(s["occ"], s["zones"])
    zsum = occ_mod.zone_summary(df)
    inc = occ_mod.detect_incidents(df, occ_mod.THRESH_OVER)
    return {"df": df, "zsum": zsum, "incidents": inc}


def select_recent(s: State):
    data_end = s["df"]["timestamp"].max()
    cutoff = data_end - pd.Timedelta(days=s["days"])
    inc = s["incidents"]
    recent = inc[inc["end_time"] >= cutoff]
    underused = s["zsum"][s["zsum"]["status"] == "Underused"]
    return {"data_end": data_end, "recent": recent, "underused": underused}


def forecast_risk(s: State):
    fc = s["forecast"]
    if fc is None or fc.empty:
        return {"near_full": pd.DataFrame()}
    nf = fc[fc["risk"] == "Near full"].sort_values(["facility_id", "zone", "timestamp"]).copy()
    if nf.empty:
        return {"near_full": nf}
    nf["grp"] = nf.groupby(["facility_id", "zone"])["timestamp"].transform(
        lambda x: (x.diff() > pd.Timedelta(hours=1)).cumsum())
    out = (nf.groupby(["facility_id", "zone", "grp"])
           .agg(start=("timestamp", "min"), end=("timestamp", "max"), peak=("predicted_utilization", "max"))
           .reset_index())
    return {"near_full": out}


def build_alerts(s: State):
    names, ztype = occ_mod.FACILITY_NAMES, {(r.facility_id, r.zone): r.zone_type for r in s["zsum"].itertuples()}
    alerts = []
    for r in s["recent"].itertuples():
        fac = names[r.facility_id]
        msg = (f"{r.zone} at {fac} reached {r.peak_count} people (capacity {r.capacity}, "
               f"{r.peak_utilization:.0f}%) for {r.hours} hour(s) from {r.start_time:%d %b %H:%M}.")
        alerts.append(dict(
            facility_id=int(r.facility_id), alert_type="overcrowding", severity=r.severity, event_time=r.start_time,
            title=f"Overcrowding: {r.zone}", message=msg,
            recommended_action=ACTIONS.get(ztype.get((r.facility_id, r.zone)), DEFAULT_ACTION),
            escalate_to="Facility manager", evidence=f"peak {r.peak_count} of {r.capacity}, {r.hours} h",
            key=f"occ|{r.facility_id}|overcrowding|{r.zone}|{r.start_time:%Y%m%d%H%M}",
            facts=dict(facility=fac, zone=r.zone, people=int(r.peak_count), capacity=int(r.capacity),
                       percent_of_capacity=round(float(r.peak_utilization)), hours=int(r.hours),
                       start=f"{r.start_time:%d %b %H:%M}"),
            must_include=[r.zone, str(r.peak_count)]))
    for r in s["underused"].itertuples():
        fac = names[r.facility_id]
        alerts.append(dict(
            facility_id=int(r.facility_id), alert_type="underused_space", severity="Info", event_time=s["data_end"],
            title=f"Underused space: {r.zone}",
            message=f"{r.zone} at {fac} is only {r.busy_hours_utilization:.0f}% full in busy hours.",
            recommended_action="Share the space with other teams or reduce heating, cooling and lighting there.",
            escalate_to="Facility manager", evidence=f"{r.busy_hours_utilization:.0f}% busy-hours utilization",
            key=f"occ|{r.facility_id}|underused|{r.zone}|{s['data_end']:%Y%m%d}",
            facts=dict(facility=fac, zone=r.zone, busy_hours_percent_full=round(float(r.busy_hours_utilization))),
            must_include=[r.zone]))
    nf = s["near_full"]
    for r in (nf.itertuples() if len(nf) else []):
        fac = names[r.facility_id]
        alerts.append(dict(
            facility_id=int(r.facility_id), alert_type="forecast_near_full", severity="Medium", event_time=r.start,
            title=f"Forecast: {r.zone} near full",
            message=f"{r.zone} at {fac} is forecast to reach {r.peak:.0f}% of capacity from {r.start:%d %b %H:%M}.",
            recommended_action="Plan seating or staffing ahead of time.", escalate_to="Facility manager",
            evidence=f"forecast peak {r.peak:.0f}%",
            key=f"occ|{r.facility_id}|forecast|{r.zone}|{r.start:%Y%m%d%H%M}",
            facts=dict(facility=fac, zone=r.zone, forecast_percent=round(float(r.peak)), start=f"{r.start:%d %b %H:%M}"),
            must_include=[r.zone]))
    alerts.sort(key=lambda a: (SEVERITY_RANK[a["severity"]], a["event_time"]))
    return {"alerts": alerts}


def reword(s: State):
    msgs, used = llm_reword(s["alerts"])
    for a, m in zip(s["alerts"], msgs):
        a["message"] = m
    return {"alerts": s["alerts"], "used_llm": used}


def save(s: State):
    engine = get_engine()
    now = datetime.now()
    rows = [dict(facility_id=a["facility_id"], agent="occupancy", alert_type=a["alert_type"],
                 severity=a["severity"], event_time=a["event_time"], created_at=now, title=a["title"],
                 message=a["message"], recommended_action=a["recommended_action"],
                 escalate_to=a["escalate_to"], evidence=a["evidence"], status="open",
                 run_id=s["run_id"], dedupe_key=a["key"]) for a in s["alerts"]]
    df = pd.DataFrame(rows, columns=SAVE_COLS)
    created, skipped = save_alerts(engine, TABLE, df, s["dry_run"])
    log_run(engine, s["run_id"], "occupancy", s["started"], "ok", created, skipped, s["used_llm"],
            f"window={s['days']}d, incidents_in_window={len(s['recent'])}", s["dry_run"])
    return {"created": created, "skipped": skipped}


def report_stop(s: State):
    print("\nOccupancy Agent STOPPED. The data failed the checks:")
    for p in s["problems"]:
        print("  -", p)
    if not s["dry_run"]:
        log_run(get_engine(), s["run_id"], "occupancy", s["started"], "stopped", 0, 0, False,
                "; ".join(s["problems"]), False)
    return {"created": 0, "skipped": 0, "alerts": []}


def route(s: State):
    return "stop" if s["stop"] else "go"


def build_graph():
    g = StateGraph(State)
    for name, fn in [("load_data", load_data), ("validate_data", validate_data), ("analyze", analyze),
                     ("select_recent", select_recent), ("forecast_risk", forecast_risk),
                     ("build_alerts", build_alerts), ("reword", reword), ("save", save),
                     ("report_stop", report_stop)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_data")
    g.add_edge("load_data", "validate_data")
    g.add_conditional_edges("validate_data", route, {"stop": "report_stop", "go": "analyze"})
    for a, b in [("analyze", "select_recent"), ("select_recent", "forecast_risk"),
                 ("forecast_risk", "build_alerts"), ("build_alerts", "reword"), ("reword", "save"),
                 ("save", END), ("report_stop", END)]:
        g.add_edge(a, b)
    return g.compile()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show alerts but save nothing")
    ap.add_argument("--days", type=int, default=14, help="look-back window in days (from the end of the data)")
    args = ap.parse_args()
    out = build_graph().invoke({"dry_run": args.dry_run, "days": args.days, "started": datetime.now(),
                                "run_id": new_run_id("occupancy")})
    if out.get("stop"):
        return
    pd.set_option("display.width", 200)
    print(f"\nOccupancy Agent {'(DRY RUN) ' if args.dry_run else ''}finished. Window: last {args.days} days "
          f"up to {out['data_end']:%d %b %Y %H:%M}")
    verb = "would save" if args.dry_run else "saved new"
    print(f"Alerts found: {len(out['alerts'])} | {verb}: {out['created']} | already existed: {out['skipped']} "
          f"| Claude wording: {'yes' if out['used_llm'] else 'no (rule-based text)'}\n")
    for a in out["alerts"]:
        print(f"[{a['severity']:8s}] {a['title']} ({occ_mod.FACILITY_NAMES[a['facility_id']]})")
        print(f"           {a['message']}")
        print(f"           Action: {a['recommended_action']}")


if __name__ == "__main__":
    main()
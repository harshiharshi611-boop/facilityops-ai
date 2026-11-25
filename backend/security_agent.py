"""
security_agent.py  (Milestone 3 - Step 5)
Security Agent built with LangGraph. Steps (nodes):
  load_data -> validate_data -> detect -> select_recent -> investigate
            -> build_alerts -> reword -> save          (stops early if the data is bad)

"investigate" collects evidence for each alert: the badge's other swipes around the
event, or who swiped at that door around that time. This supports incident investigation.

Run:  python security_agent.py --dry-run
      python security_agent.py
      python security_agent.py --days 30
"""
import argparse
from datetime import datetime
from typing import Any, TypedDict

import pandas as pd
from langgraph.graph import END, START, StateGraph

import security as sec
from agent_common import (SAVE_COLS, SEVERITY_RANK, get_engine, llm_reword, log_run, new_run_id, save_alerts)

TABLE = "security_alerts"
FACILITY_NAMES = {1: "Tech Park Block A", 2: "City Hospital"}
ACTIONS = {
    "repeated_denied": "Check who owns the badge. Block it if not recognised and review CCTV at the door.",
    "off_hours_restricted": "Call the badge owner and the duty manager, review CCTV of the room, and check what was accessed.",
    "impossible_travel": "Block the badge now and issue a new one. Check both entry points on CCTV.",
    "door_forced": "Send security to the door now, check CCTV and the room, and file an incident report.",
    "tailgating": "Review CCTV with the badge owner and remind staff: one person per swipe.",
    "loitering": "Send a guard to check the area and review CCTV.",
    "visitor_overstay": "Contact the host and confirm the visitor has left.",
    "visitor_no_checkout": "Ask the front desk to confirm departure and close the record.",
    "visitor_restricted_zone": "Check the host approval and escort the visitor out of the restricted room.",
}
ESCALATE = {"Critical": "Security manager + facility head (immediately)", "High": "Security desk (within 1 hour)",
            "Medium": "Security desk (same day)", "Low": "Front desk (next day)"}


class State(TypedDict, total=False):
    dry_run: bool
    days: int
    run_id: str
    started: Any
    access: Any
    cctv: Any
    visitors: Any
    zones: Any
    problems: list
    stop: bool
    events: Any
    data_end: Any
    recent: Any
    alerts: list
    used_llm: bool
    created: int
    skipped: int


# ------------------------------------------------------------------ nodes
def load_data(s: State):
    a, c, v, z = sec.load(get_engine())
    return {"access": a, "cctv": c, "visitors": v, "zones": z}


def validate_data(s: State):
    problems = sec.validate(s["access"], s["cctv"], s["visitors"])
    return {"problems": problems, "stop": bool(problems)}


def detect(s: State):
    z = s["zones"]
    restricted = set(zip(z[z.restricted].facility_id, z[z.restricted].zone))
    a, c, v = s["access"], s["cctv"], s["visitors"]
    parts = [sec.rule_repeated_denied(a, restricted), sec.rule_off_hours_restricted(a, restricted),
             sec.rule_impossible_travel(a), sec.rule_cctv(a, c), sec.rule_visitors(v, restricted)]
    ev = pd.concat([p for p in parts if len(p)], ignore_index=True)
    return {"events": ev.sort_values(["facility_id", "timestamp"]).reset_index(drop=True)}


def select_recent(s: State):
    data_end = max(s["access"]["timestamp"].max(), s["cctv"]["timestamp"].max())
    ev = s["events"]
    recent = ev[ev["timestamp"] >= data_end - pd.Timedelta(days=s["days"])].copy()
    recent["rank"] = recent["severity"].map(SEVERITY_RANK)
    recent = recent.sort_values(["rank", "timestamp"], ascending=[True, False]).drop(columns="rank")
    return {"data_end": data_end, "recent": recent.reset_index(drop=True)}


def evidence_for(r, a):
    """Short evidence text: what else happened around this event."""
    if pd.notna(r.badge_id):
        w = a[(a.badge_id == r.badge_id) & ((a.timestamp - r.timestamp).abs() <= pd.Timedelta(hours=3))] \
            .sort_values("timestamp").head(6)
        if w.empty:
            return f"badge {r.badge_id}: no other swipes within 3 hours"
        bits = [f"{t:%H:%M} {zn} {d} {res.lower()}" for t, zn, d, res in
                zip(w.timestamp, w.zone, w.direction, w.result)]
        return f"badge {r.badge_id} around the event: " + "; ".join(bits)
    if r.source == "cctv":
        w = a[(a.facility_id == r.facility_id) & (a.zone == r.zone) &
              ((a.timestamp - r.timestamp).abs() <= pd.Timedelta(minutes=5))]
        if w.empty:
            return f"no badge swipes at {r.zone} within 5 minutes"
        return f"{len(w)} swipe(s) at {r.zone} within 5 minutes: " + ", ".join(sorted(set(w.badge_id))[:5])
    return "see the visitor record"


def investigate(s: State):
    a = s["access"]
    ev = s["recent"].copy()
    ev["evidence"] = [evidence_for(r, a) for r in ev.itertuples()]
    return {"recent": ev}


def build_alerts(s: State):
    alerts = []
    for r in s["recent"].itertuples():
        fac = FACILITY_NAMES[r.facility_id]
        who = f" Badge: {r.badge_id}." if pd.notna(r.badge_id) else ""
        msg = f"{r.description} ({fac}, {r.timestamp:%d %b %H:%M}).{who}"
        must = [r.zone] + ([r.badge_id] if pd.notna(r.badge_id) else [])
        alerts.append(dict(
            facility_id=int(r.facility_id), alert_type=r.event_type, severity=r.severity, event_time=r.timestamp,
            title=f"{r.event_type.replace('_', ' ').capitalize()}: {r.zone}", message=msg,
            recommended_action=ACTIONS[r.event_type], escalate_to=ESCALATE[r.severity], evidence=r.evidence,
            key=f"sec|{r.facility_id}|{r.event_type}|{r.zone}|{r.timestamp:%Y%m%d%H%M%S}|{r.badge_id}",
            facts=dict(facility=fac, event=r.description, zone=r.zone, time=f"{r.timestamp:%d %b %H:%M}",
                       badge=None if pd.isna(r.badge_id) else r.badge_id, severity=r.severity),
            must_include=must))
    return {"alerts": alerts}


def reword(s: State):
    msgs, used = llm_reword(s["alerts"])
    for a, m in zip(s["alerts"], msgs):
        a["message"] = m
    return {"alerts": s["alerts"], "used_llm": used}


def save(s: State):
    engine = get_engine()
    now = datetime.now()
    rows = [dict(facility_id=a["facility_id"], agent="security", alert_type=a["alert_type"],
                 severity=a["severity"], event_time=a["event_time"], created_at=now, title=a["title"],
                 message=a["message"], recommended_action=a["recommended_action"],
                 escalate_to=a["escalate_to"], evidence=a["evidence"], status="open",
                 run_id=s["run_id"], dedupe_key=a["key"]) for a in s["alerts"]]
    df = pd.DataFrame(rows, columns=SAVE_COLS)
    created, skipped = save_alerts(engine, TABLE, df, s["dry_run"])
    log_run(engine, s["run_id"], "security", s["started"], "ok", created, skipped, s["used_llm"],
            f"window={s['days']}d, events_in_window={len(s['recent'])}, events_total={len(s['events'])}",
            s["dry_run"])
    return {"created": created, "skipped": skipped}


def report_stop(s: State):
    print("\nSecurity Agent STOPPED. The data failed the checks:")
    for p in s["problems"]:
        print("  -", p)
    if not s["dry_run"]:
        log_run(get_engine(), s["run_id"], "security", s["started"], "stopped", 0, 0, False,
                "; ".join(s["problems"]), False)
    return {"created": 0, "skipped": 0, "alerts": []}


def route(s: State):
    return "stop" if s["stop"] else "go"


def build_graph():
    g = StateGraph(State)
    for name, fn in [("load_data", load_data), ("validate_data", validate_data), ("detect", detect),
                     ("select_recent", select_recent), ("investigate", investigate),
                     ("build_alerts", build_alerts), ("reword", reword), ("save", save),
                     ("report_stop", report_stop)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_data")
    g.add_edge("load_data", "validate_data")
    g.add_conditional_edges("validate_data", route, {"stop": "report_stop", "go": "detect"})
    for a, b in [("detect", "select_recent"), ("select_recent", "investigate"),
                 ("investigate", "build_alerts"), ("build_alerts", "reword"), ("reword", "save"),
                 ("save", END), ("report_stop", END)]:
        g.add_edge(a, b)
    return g.compile()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show alerts but save nothing")
    ap.add_argument("--days", type=int, default=14, help="look-back window in days (from the end of the data)")
    args = ap.parse_args()
    out = build_graph().invoke({"dry_run": args.dry_run, "days": args.days, "started": datetime.now(),
                                "run_id": new_run_id("security")})
    if out.get("stop"):
        return
    print(f"\nSecurity Agent {'(DRY RUN) ' if args.dry_run else ''}finished. Window: last {args.days} days "
          f"up to {out['data_end']:%d %b %Y %H:%M} (all-time events detected: {len(out['events'])})")
    verb = "would save" if args.dry_run else "saved new"
    print(f"Alerts in window: {len(out['alerts'])} | {verb}: {out['created']} | already existed: {out['skipped']} "
          f"| Claude wording: {'yes' if out['used_llm'] else 'no (rule-based text)'}\n")
    for a in out["alerts"]:
        print(f"[{a['severity']:8s}] {a['title']} ({FACILITY_NAMES[a['facility_id']]})")
        print(f"           {a['message']}")
        print(f"           Action: {a['recommended_action']}")
        print(f"           Escalate to: {a['escalate_to']}")
        print(f"           Evidence: {a['evidence']}")


if __name__ == "__main__":
    main()
import os
import sys
import json
from typing import TypedDict, Any

import anthropic
import joblib
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from langgraph.graph import StateGraph, START, END

import health as health_mod
import behavior as behavior_mod
import predict as predict_mod
import schedule as schedule_mod

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL) if DB_URL else None
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

AGENT_NAME = "Maintenance Agent"
MIN_DAYS_OF_DATA = 14       # a machine needs at least 14 days of readings
MIN_BREAKDOWNS = 3          # the model needs some breakdown history to learn from
CHANNELS = ["temperature_c", "vibration_mm_s", "current_amp"]
ASSET_COLS = ["asset_id", "facility_id", "asset_name", "asset_type", "criticality"]


class AgentState(TypedDict, total=False):
    data: Any
    persist: bool
    issues: list
    stop: bool
    health_df: Any
    scored: Any
    events: Any
    pred: Any
    sched: Any
    explanations: dict
    summary: str
    source: str
    alerts: Any
    orders: Any
    steps: list


# ------------------------------------------------------------ 1. load
def load_all():
    assets = pd.read_sql(text("SELECT * FROM assets"), engine,
                         parse_dates=["install_date", "last_service_date"])
    sensors = pd.read_sql(
        text("SELECT asset_id, timestamp, temperature_c, vibration_mm_s, "
             "current_amp FROM sensor_readings"),
        engine, parse_dates=["timestamp"])
    maint = pd.read_sql(
        text("SELECT asset_id, issue_type, maintenance_type, maintenance_date, "
             "status, cost_rs, downtime_hours FROM maintenance_records"),
        engine, parse_dates=["maintenance_date"])
    for c in CHANNELS:
        sensors[c] = sensors[c].astype(float)
    for c in ["cost_rs", "downtime_hours"]:
        maint[c] = maint[c].astype(float)
    return assets, sensors, maint


def load_node(state):
    if state.get("data") is not None:
        assets, sensors, maint = state["data"]
        msg = "load: using the data that was passed in"
    else:
        assets, sensors, maint = load_all()
        msg = (f"load: {len(assets)} assets, {len(sensors)} sensor readings, "
               f"{len(maint)} maintenance records")
    return {"data": (assets, sensors, maint), "steps": state["steps"] + [msg]}


# ------------------------------------------------------------ 2. validate
def validate_node(state):
    assets, sensors, maint = state["data"]
    issues = []

    n = len(sensors)
    sensors = sensors.drop_duplicates(subset=["asset_id", "timestamp"])
    if len(sensors) < n:
        issues.append(f"Removed {n - len(sensors)} duplicate readings")

    n = len(sensors)
    sensors = sensors.dropna(subset=CHANNELS)
    if len(sensors) < n:
        issues.append(f"Removed {n - len(sensors)} readings with missing values")

    n = len(sensors)
    sensors = sensors[(sensors.vibration_mm_s >= 0) & (sensors.current_amp >= 0)]
    if len(sensors) < n:
        issues.append(f"Removed {n - len(sensors)} readings with negative vibration or current")

    short = []
    if len(sensors):
        g = sensors.groupby("asset_id").timestamp
        span = (g.max() - g.min()).dt.days
        short = span[span < MIN_DAYS_OF_DATA].index
    if len(short):
        sensors = sensors[~sensors.asset_id.isin(short)]
        issues.append(f"{len(short)} machine(s) have under {MIN_DAYS_OF_DATA} days of data and were skipped")

    assets = assets[assets.asset_id.isin(sensors.asset_id)].reset_index(drop=True)
    sensors = sensors.reset_index(drop=True)

    stop = False
    if sensors.empty or assets.empty:
        issues.append("No usable sensor data")
        stop = True
    elif (maint.maintenance_type == "breakdown").sum() < MIN_BREAKDOWNS:
        issues.append(f"Fewer than {MIN_BREAKDOWNS} breakdowns on record: not enough to train the model")
        stop = True

    return {"data": (assets, sensors, maint), "issues": issues, "stop": stop,
            "steps": state["steps"] + [f"validate: {len(sensors)} clean readings, "
                                       f"{len(issues)} issue(s)" + (", stopping" if stop else "")]}


def route_after_validate(state):
    return "end" if state.get("stop") else "score_health"


# ------------------------------------------------------------ 3. health
def score_health_node(state):
    assets, sensors, maint = state["data"]
    h = health_mod.compute_health(assets, sensors, maint)
    low = int((h.health_score < 70).sum())
    return {"health_df": h, "steps": state["steps"]
            + [f"score_health: {len(h)} machines scored, {low} below 70"]}


# ------------------------------------------------------------ 4. detect
def detect_node(state):
    _, sensors, maint = state["data"]
    scored = behavior_mod.score_readings(sensors)
    events = behavior_mod.build_events(scored, maint)
    ongoing = int((events.event_type == "Ongoing").sum()) if len(events) else 0
    return {"scored": scored, "events": events, "steps": state["steps"]
            + [f"detect: {len(events)} abnormal-behavior events, {ongoing} ongoing"]}


# ------------------------------------------------------------ 5. predict
def get_model(s, maint):
    path = predict_mod.MODEL_PATH
    if os.path.exists(path):
        try:
            return joblib.load(path)["model"], "saved model"
        except Exception:
            pass
    snap = predict_mod.make_snapshots(s, maint)
    model = predict_mod.new_forest().fit(snap[predict_mod.FEATURES], snap.y)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    joblib.dump({"model": model, "features": predict_mod.FEATURES,
                 "horizon_days": predict_mod.HORIZON_DAYS}, path)
    return model, "newly trained model"


def predict_node(state):
    assets, _, maint = state["data"]
    s = predict_mod.add_features(state["scored"].copy())
    model, how = get_model(s, maint)
    pred = predict_mod.predict_now(model, s, assets[ASSET_COLS])
    n = int(pred.will_fail_14d.sum())
    return {"pred": pred, "steps": state["steps"]
            + [f"predict: {n} machine(s) likely to fail within "
               f"{predict_mod.HORIZON_DAYS} days ({how})"]}


# ------------------------------------------------------------ 6. plan
def plan_node(state):
    assets, _, maint = state["data"]
    pred = state["pred"]
    keep = ["asset_id", "facility_id", "asset_name", "asset_type", "criticality",
            "last_service_date", "service_interval_days"]
    sched = schedule_mod.build_schedule(
        assets[keep], state["health_df"][["asset_id", "health_score", "status"]],
        pred[["asset_id", "risk_pct", "risk_level", "will_fail_14d", "reason", "predicted_at"]],
        maint, pred.predicted_at.max())
    em = int((sched.priority_label == "Emergency").sum()) if len(sched) else 0
    return {"sched": sched, "steps": state["steps"]
            + [f"plan: {len(sched)} jobs scheduled, {em} emergency"]}


# ------------------------------------------------------------ 7. explain
CHECKS = {
    "Vibration": ["Check bearing condition and shaft alignment",
                  "Re-lubricate and tighten mounting bolts",
                  "Measure vibration again after the service"],
    "Temperature": ["Check cooling, airflow and filters",
                    "Check lubrication and refrigerant levels",
                    "Measure temperature again after the service"],
    "Current": ["Check motor windings and belts",
                "Tighten electrical connections",
                "Measure current again after the service"],
    "Routine": ["Complete the standard service checklist",
                "Replace filters and worn parts as needed",
                "Update the service log"],
}

SYSTEM = ("You are a maintenance planner writing for a facility manager. "
          "Use ONLY the facts provided. Never invent numbers. Write money as 'Rs'. "
          "Keep the language simple. Reply with one JSON object only, no markdown.")


def check_key(reason):
    r = str(reason)
    for k in ("Vibration", "Temperature", "Current"):
        if r.startswith(k):
            return k
    return "Routine"


def rule_based(sched):
    expl = {}
    for j in sched.itertuples():
        evidence = j.reason.split(": ", 1)[-1] if j.priority_label in ("Emergency", "Urgent") else j.reason
        if j.priority_label in ("Emergency", "Urgent", "Planned") and j.risk_pct >= 25:
            text_ = (f"{evidence}. Failure risk is {j.risk_pct:.0f}% within 14 days and the "
                     f"health score is {j.health_score:.0f}. Service by {pd.Timestamp(j.recommended_date):%d %b}.")
            key = check_key(evidence)
        else:
            text_ = f"{j.reason}. Service on {pd.Timestamp(j.recommended_date):%d %b} keeps the machine reliable."
            key = "Routine"
        expl[int(j.asset_id)] = (text_, CHECKS[key])
    return expl


def rule_based_summary(sched):
    em = sched[sched.priority_label == "Emergency"]
    other = len(sched) - len(em)
    parts = []
    if len(em):
        names = ", ".join(f"{r.asset_name} (facility {r.facility_id})" for r in em.itertuples())
        day = pd.Timestamp(em.recommended_date.min())
        parts.append(f"{len(em)} machine(s) need emergency service on {day:%d %b}: {names}.")
    else:
        parts.append("No machine needs emergency service.")
    parts.append(f"{other} planned and routine jobs are scheduled over the next 30 days.")
    saving = sched.potential_saving_rs.sum()
    if saving > 0:
        parts.append(f"Acting in time could avoid about Rs {saving:,.0f} and "
                     f"{sched.downtime_avoided_hours.sum():.0f} hours of downtime (estimate).")
    return " ".join(parts)


def parse_llm(raw, valid_ids):
    raw = raw.strip().replace("```json", "").replace("```", "").strip()
    obj = json.loads(raw)
    summary = str(obj["summary"]).strip()
    out = {}
    for item in obj["jobs"]:
        aid = int(item["asset_id"])
        if aid in valid_ids:
            checks = [str(c) for c in item.get("checks", [])][:4]
            out[aid] = (str(item["explanation"]).strip(), checks)
    if not summary or not out:
        raise ValueError("LLM answer had no usable content")
    return summary, out


def llm_explain(facts):
    client = anthropic.Anthropic()
    prompt = ("Maintenance plan facts:\n" + json.dumps(facts, indent=2)
              + "\n\nReturn a JSON object with two keys. "
                "'summary': at most 4 simple sentences for the facility manager. "
                "'jobs': an array with one item per machine, each with "
                "'asset_id' (number), 'explanation' (1-2 simple sentences on why this machine needs service now), "
                "and 'checks' (an array of 2-3 short inspection steps).")
    resp = client.messages.create(model=MODEL, max_tokens=1800, system=SYSTEM,
                                  messages=[{"role": "user", "content": prompt}])
    return resp.content[0].text


def explain_node(state):
    sched = state["sched"]
    if sched is None or sched.empty:
        return {"explanations": {}, "summary": "No maintenance jobs are needed.",
                "source": "rule-based fallback",
                "steps": state["steps"] + ["explain: nothing to explain"]}
    expl = rule_based(sched)
    summary = rule_based_summary(sched)
    source = "rule-based fallback"

    top = sched[sched.priority_label != "Routine"]
    facts = [dict(asset_id=int(j.asset_id), machine=j.asset_name, facility=int(j.facility_id),
                  type=j.asset_type, criticality=int(j.criticality), priority=j.priority_label,
                  service_date=str(j.recommended_date), failure_risk_pct=round(float(j.risk_pct)),
                  health_score=round(float(j.health_score)), evidence=j.reason,
                  potential_saving_rs=float(j.potential_saving_rs))
             for j in top.itertuples()]
    if facts:
        try:
            llm_summary, llm_expl = parse_llm(llm_explain(facts), {f["asset_id"] for f in facts})
            summary = llm_summary
            expl.update(llm_expl)
            source = MODEL
        except Exception as e:
            print("LLM unavailable, using rule-based fallback:", e)
    return {"explanations": expl, "summary": summary, "source": source,
            "steps": state["steps"] + [f"explain: wording written by {source}"]}


# ------------------------------------------------------------ 8. tickets
LABEL_TO_PRIORITY = {"Emergency": "critical", "Urgent": "high",
                     "Planned": "medium", "Routine": "low"}
LABEL_TO_SEVERITY = {"Emergency": "critical", "Urgent": "high", "Planned": "medium"}
NOTIFY = {"critical": "Facility manager and maintenance lead, immediately",
          "high": "Maintenance lead, same day",
          "medium": "Maintenance team, next working day"}


def alert_type(j):
    if j.risk_pct >= 50:
        return "Predicted failure"
    if j.risk_pct >= 25:
        return "Elevated risk"
    if j.health_score < 70:
        return "Low health"
    return "Service overdue"


def create_tickets_node(state):
    sched, expl, source = state["sched"], state["explanations"], state["source"]
    as_of = state["pred"].predicted_at.max()
    orders, alerts = [], []
    for j in sched.itertuples():
        why, checks = expl[int(j.asset_id)]
        desc = why + " Checks: " + "; ".join(checks) + "."
        if j.note:
            desc += f" ({j.note}.)"
        orders.append(dict(
            asset_id=int(j.asset_id), created_at=as_of,
            priority=LABEL_TO_PRIORITY[j.priority_label],
            title=f"{j.task} - {j.asset_name}"[:200], description=desc,
            due_date=pd.Timestamp(j.recommended_date), status="open",
            source=f"{AGENT_NAME} ({source})"[:60]))
        if j.priority_label in LABEL_TO_SEVERITY:
            sev = LABEL_TO_SEVERITY[j.priority_label]
            typ = alert_type(j)
            alerts.append(dict(
                facility_id=int(j.facility_id), asset_id=int(j.asset_id), source=AGENT_NAME,
                alert_type=typ, severity=sev, title=f"{typ}: {j.asset_name}"[:200],
                message=f"{j.reason}. Recommended service: {pd.Timestamp(j.recommended_date):%d %b}.",
                notify=NOTIFY[sev], status="open", created_at=as_of))
    orders, alerts = pd.DataFrame(orders), pd.DataFrame(alerts)
    return {"orders": orders, "alerts": alerts, "steps": state["steps"]
            + [f"create_tickets: {len(orders)} work orders, {len(alerts)} alerts prepared"]}


# ------------------------------------------------------------ 9. save
ALERTS_DDL = """
CREATE TABLE IF NOT EXISTS alerts (
    alert_id    SERIAL PRIMARY KEY,
    facility_id INT REFERENCES facilities(facility_id),
    asset_id    INT,
    source      VARCHAR(40),
    alert_type  VARCHAR(40),
    severity    VARCHAR(10),
    title       VARCHAR(200),
    message     TEXT,
    notify      VARCHAR(100),
    status      VARCHAR(20) DEFAULT 'open',
    created_at  TIMESTAMP
)
"""
RUNS_DDL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      SERIAL PRIMARY KEY,
    agent       VARCHAR(40),
    finished_at TIMESTAMP DEFAULT NOW(),
    source      VARCHAR(60),
    jobs        INT,
    alerts      INT,
    emergencies INT,
    summary     TEXT,
    steps       TEXT
)
"""


def save_predictions_only(pred):
    # failure_predictions is refreshed in place so the Step 4 metrics table is kept
    out = pred[["asset_id", "facility_id", "asset_name", "asset_type", "criticality",
                "risk_pct", "risk_level", "will_fail_14d", "reason", "predicted_at"]].copy()
    out["horizon_days"] = predict_mod.HORIZON_DAYS
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM failure_predictions"))
    out.to_sql("failure_predictions", engine, if_exists="append", index=False)


def save_node(state):
    steps = state["steps"]
    if not state.get("persist", True):
        return {"steps": steps + ["save: skipped (dry run, nothing written)"]}

    health_mod.save_health(state["health_df"])
    behavior_mod.save_events(state["events"])
    save_predictions_only(state["pred"])
    schedule_mod.save_schedule(state["sched"])

    orders, alerts = state["orders"], state["alerts"]
    with engine.begin() as conn:
        conn.execute(text(ALERTS_DDL))
        conn.execute(text(RUNS_DDL))
        conn.execute(text("DELETE FROM work_orders WHERE source LIKE :s"),
                     {"s": AGENT_NAME + "%"})
        conn.execute(text("DELETE FROM alerts WHERE source = :s"), {"s": AGENT_NAME})
    if len(orders):
        orders.to_sql("work_orders", engine, if_exists="append", index=False)
    if len(alerts):
        alerts.to_sql("alerts", engine, if_exists="append", index=False)

    steps = steps + [f"save: {len(orders)} work orders and {len(alerts)} alerts written to PostgreSQL"]
    em = int((state["sched"].priority_label == "Emergency").sum())
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO agent_runs (agent, source, jobs, alerts, emergencies, summary, steps) "
                 "VALUES (:a, :src, :j, :al, :em, :sm, :st)"),
            {"a": AGENT_NAME, "src": state["source"], "j": len(orders), "al": len(alerts),
             "em": em, "sm": state["summary"], "st": json.dumps(steps)})
    return {"steps": steps}


# ------------------------------------------------------------ the graph
graph = StateGraph(AgentState)
graph.add_node("load", load_node)
graph.add_node("validate", validate_node)
graph.add_node("score_health", score_health_node)
graph.add_node("detect", detect_node)
graph.add_node("predict", predict_node)
graph.add_node("plan", plan_node)
graph.add_node("explain", explain_node)
graph.add_node("create_tickets", create_tickets_node)
graph.add_node("save", save_node)

graph.add_edge(START, "load")
graph.add_edge("load", "validate")
graph.add_conditional_edges("validate", route_after_validate,
                            {"score_health": "score_health", "end": END})
graph.add_edge("score_health", "detect")
graph.add_edge("detect", "predict")
graph.add_edge("predict", "plan")
graph.add_edge("plan", "explain")
graph.add_edge("explain", "create_tickets")
graph.add_edge("create_tickets", "save")
graph.add_edge("save", END)

agent = graph.compile()


def run_maintenance_agent(save=True, data=None):
    result = agent.invoke({"data": data, "persist": save, "steps": []})
    sched, alerts = result.get("sched"), result.get("alerts")
    jobs = []
    if sched is not None and len(sched):
        for j in sched.itertuples():
            jobs.append(dict(
                asset_id=int(j.asset_id), asset_name=j.asset_name, facility_id=int(j.facility_id),
                priority=j.priority_label, priority_score=float(j.priority_score),
                task=j.task, recommended_date=str(j.recommended_date),
                explanation=result["explanations"][int(j.asset_id)][0]))
    return dict(steps=result["steps"], issues=result.get("issues", []),
                source=result.get("source"), summary=result.get("summary"),
                jobs=jobs,
                alerts=[] if alerts is None else alerts.assign(
                    created_at=alerts.created_at.astype(str)).to_dict("records"))


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    out = run_maintenance_agent(save=not dry)

    print("\nAGENT STEPS")
    for i, s in enumerate(out["steps"], 1):
        print(f"  {i}. {s}")
    if out["issues"]:
        print("\nDATA ISSUES")
        for i in out["issues"]:
            print("  -", i)
    if out["jobs"]:
        print(f"\nSUMMARY FOR THE FACILITY MANAGER (written by {out['source']})")
        print(" ", out["summary"])
        print("\nALERTS")
        for a in out["alerts"]:
            print(f"  [{a['severity'].upper():8s}] {a['title']}")
            print(f"             {a['message']}")
            print(f"             notify: {a['notify']}")
        print("\nWORK ORDERS (most urgent first)")
        for j in out["jobs"][:6]:
            print(f"  {j['recommended_date']}  {j['asset_name']:16s} fac {j['facility_id']}  "
                  f"{j['priority']:9s} {j['task']}")
        if len(out["jobs"]) > 6:
            print(f"  + {len(out['jobs']) - 6} more")
    print("\nWORKFLOW DIAGRAM (paste into mermaid.live)")
    print(agent.get_graph().draw_mermaid())
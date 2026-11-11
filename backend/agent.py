import os
import json
from typing import TypedDict, Any

import anthropic
from dotenv import load_dotenv
from sqlalchemy import text
from langgraph.graph import StateGraph, START, END

from analytics import load_energy, engine, TARIFF
from anomaly import detect_zscore, MESSAGES, FEATURES

load_dotenv()
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
NUM_COLS = FEATURES + ["electricity_usage"]


class AgentState(TypedDict, total=False):
    facility_id: int
    df: Any
    issues: list
    stop: bool
    anomalies: Any
    findings: dict
    recommendations: list
    source: str
    steps: list


def load_node(state):
    df = load_energy(state["facility_id"])
    return {"df": df,
            "steps": state["steps"] + [f"load: {len(df)} rows read"]}


def validate_node(state):
    df = state["df"]
    issues = []

    n = len(df)
    df = df.drop_duplicates(subset=["facility_id", "timestamp"])
    if len(df) < n:
        issues.append(f"Removed {n - len(df)} duplicate rows")

    n = len(df)
    df = df.dropna(subset=NUM_COLS)
    if len(df) < n:
        issues.append(f"Removed {n - len(df)} rows with missing values")

    n = len(df)
    df = df[(df[NUM_COLS] >= 0).all(axis=1)]
    if len(df) < n:
        issues.append(f"Removed {n - len(df)} rows with negative readings")

    df = df.reset_index(drop=True)
    stop = len(df) < 24 * 7
    if stop:
        issues.append("Not enough data (need at least 7 days)")

    return {"df": df, "issues": issues, "stop": stop,
            "steps": state["steps"]
            + [f"validate: {len(df)} clean rows, {len(issues)} issue(s)"]}


def route_after_validate(state):
    return "end" if state.get("stop") else "detect"


def detect_node(state):
    df = detect_zscore(state["df"])
    flagged = df[df["pred_zscore"] == 1].copy()
    return {"df": df, "anomalies": flagged,
            "steps": state["steps"]
            + [f"detect: {len(flagged)} anomalous hours found"]}


def analyze_node(state):
    df, a = state["df"], state["anomalies"]
    days = max(df["timestamp"].dt.date.nunique(), 1)
    total = df["electricity_usage"].sum()
    off = df[~df["is_working"]]
    night = df[df["hour"].between(0, 5)]
    work = df[df["is_working"]]

    by_type, top_hours, excess_kwh = [], [], 0.0
    if len(a):
        g = a.groupby("worst_feature").agg(
            count=("max_z", "size"), excess=("excess_kwh", "sum"))
        for feat, row in g.iterrows():
            by_type.append({"issue": MESSAGES[feat],
                            "count": int(row["count"]),
                            "excess_kwh": round(float(row["excess"]), 1)})
        by_type.sort(key=lambda x: x["excess_kwh"], reverse=True)
        top_hours = [int(h) for h in a["hour"].value_counts().head(3).index]
        excess_kwh = float(a["excess_kwh"].sum())

    findings = {
        "days_analyzed": int(days),
        "total_kwh": round(float(total)),
        "off_hours_share_pct": round(float(off["electricity_usage"].sum() / total * 100), 1),
        "night_hvac_avg_kwh": round(float(night["hvac_kwh"].mean()), 1),
        "working_hvac_avg_kwh": round(float(work["hvac_kwh"].mean()), 1),
        "night_lighting_avg_kwh": round(float(night["lighting_kwh"].mean()), 1),
        "anomaly_count": int(len(a)),
        "anomaly_rate_pct": round(len(a) / len(df) * 100, 1),
        "anomalies_by_type": by_type,
        "top_anomaly_hours": top_hours,
        "anomaly_cost_rs_per_month": round(excess_kwh * TARIFF / days * 30),
        "hvac_setback_saving_rs_per_month": round(
            float(off["hvac_kwh"].sum()) * 0.20 * TARIFF / days * 30),
        "assumption": "HVAC setback assumed to cut off-hours HVAC by 20%",
    }
    return {"findings": findings,
            "steps": state["steps"] + ["analyze: waste patterns calculated"]}


SYSTEM = ("You are an energy-efficiency advisor for a facility manager. "
          "Use ONLY the numbers in the data provided. Never invent figures. "
          "Write money as 'Rs'. Reply with a JSON array only, no markdown.")


def llm_recommendations(findings):
    client = anthropic.Anthropic()
    prompt = (
        "Facility energy findings:\n" + json.dumps(findings, indent=2)
        + "\n\nGive 3 to 5 recommendations as a JSON array. Each item has: "
        "title (max 8 words), detail (1-2 simple sentences citing numbers "
        "from the data), priority (high, medium or low), "
        "est_monthly_saving_rs (a number that comes from the data)."
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=1200, system=SYSTEM,
        messages=[{"role": "user", "content": prompt}])
    raw = resp.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return [{"title": str(r["title"]),
             "detail": str(r["detail"]),
             "priority": str(r.get("priority", "medium")).lower(),
             "est_monthly_saving_rs": float(r.get("est_monthly_saving_rs", 0))}
            for r in json.loads(raw)]


def rule_based(f):
    recs = [{
        "title": "Schedule HVAC setback after hours",
        "detail": (f"Overnight HVAC averages {f['night_hvac_avg_kwh']} kWh per hour. "
                   f"A 20% setback could save about Rs "
                   f"{f['hvac_setback_saving_rs_per_month']} per month."),
        "priority": "medium",
        "est_monthly_saving_rs": f["hvac_setback_saving_rs_per_month"]}]
    if f["anomaly_count"]:
        recs.append({
            "title": "Investigate recurring abnormal hours",
            "detail": (f"{f['anomaly_count']} abnormal hours found, mostly around "
                       f"hours {f['top_anomaly_hours']}. They waste about Rs "
                       f"{f['anomaly_cost_rs_per_month']} per month."),
            "priority": "high",
            "est_monthly_saving_rs": f["anomaly_cost_rs_per_month"]})
    if f["anomalies_by_type"]:
        top = f["anomalies_by_type"][0]
        recs.append({
            "title": f"Fix: {top['issue']}",
            "detail": (f"This is the biggest source of waste: {top['count']} events, "
                       f"{top['excess_kwh']} extra kWh."),
            "priority": "high",
            "est_monthly_saving_rs": 0})
    return recs


def recommend_node(state):
    f = state["findings"]
    try:
        recs, source = llm_recommendations(f), MODEL
    except Exception as e:
        print("LLM unavailable, using rule-based fallback:", e)
        recs, source = rule_based(f), "rule-based fallback"
    return {"recommendations": recs, "source": source,
            "steps": state["steps"]
            + [f"recommend: {len(recs)} recommendations from {source}"]}


DDL = """
CREATE TABLE IF NOT EXISTS energy_recommendations (
    rec_id        SERIAL PRIMARY KEY,
    facility_id   INT REFERENCES facilities(facility_id),
    created_at    TIMESTAMP DEFAULT NOW(),
    title         VARCHAR(200),
    detail        TEXT,
    priority      VARCHAR(10),
    est_saving_rs NUMERIC,
    source        VARCHAR(60)
);
"""


def save_node(state):
    fid = state["facility_id"]
    rows = [{"fid": fid, "title": r["title"], "detail": r["detail"],
             "priority": r["priority"], "saving": r["est_monthly_saving_rs"],
             "source": state["source"]} for r in state["recommendations"]]
    with engine.begin() as conn:
        conn.execute(text(DDL))
        conn.execute(text("DELETE FROM energy_recommendations "
                          "WHERE facility_id = :fid"), {"fid": fid})
        if rows:
            conn.execute(text(
                "INSERT INTO energy_recommendations "
                "(facility_id, title, detail, priority, est_saving_rs, source) "
                "VALUES (:fid, :title, :detail, :priority, :saving, :source)"),
                rows)
    return {"steps": state["steps"] + [f"save: {len(rows)} rows written to PostgreSQL"]}


graph = StateGraph(AgentState)
graph.add_node("load", load_node)
graph.add_node("validate", validate_node)
graph.add_node("detect", detect_node)
graph.add_node("analyze", analyze_node)
graph.add_node("recommend", recommend_node)
graph.add_node("save", save_node)

graph.add_edge(START, "load")
graph.add_edge("load", "validate")
graph.add_conditional_edges("validate", route_after_validate,
                            {"detect": "detect", "end": END})
graph.add_edge("detect", "analyze")
graph.add_edge("analyze", "recommend")
graph.add_edge("recommend", "save")
graph.add_edge("save", END)

agent = graph.compile()


def run_energy_agent(facility_id=1):
    result = agent.invoke({"facility_id": facility_id, "steps": []})
    return {"facility_id": facility_id,
            "steps": result["steps"],
            "issues": result.get("issues", []),
            "findings": result.get("findings"),
            "recommendations": result.get("recommendations", []),
            "source": result.get("source")}


if __name__ == "__main__":
    out = run_energy_agent(1)
    print("\nAGENT STEPS")
    for s in out["steps"]:
        print("  -", s)
    print("\nFINDINGS")
    print(json.dumps(out["findings"], indent=2))
    print("\nRECOMMENDATIONS (source:", out["source"], ")")
    for r in out["recommendations"]:
        print(f"  [{r['priority'].upper()}] {r['title']}")
        print("     ", r["detail"])
    print("\nWORKFLOW DIAGRAM (paste into mermaid.live)")
    print(agent.get_graph().draw_mermaid())
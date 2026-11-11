import json
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import analytics
import anomaly
from agent import run_energy_agent

app = FastAPI(title="FacilityOps AI - Energy API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def clean(obj):
    """Convert numpy, pandas and Decimal values into plain JSON types."""
    def default(o):
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, Decimal):
            return float(o)
        return str(o)
    return json.loads(json.dumps(obj, default=default))


def check_facility(facility_id):
    if facility_id is None:
        return
    found = pd.read_sql(
        text("SELECT 1 FROM facilities WHERE facility_id = :f"),
        analytics.engine, params={"f": facility_id})
    if found.empty:
        raise HTTPException(status_code=404,
                            detail=f"Facility {facility_id} not found")


@app.get("/")
def home():
    return {"message": "FacilityOps API running", "docs": "/docs"}


@app.get("/facilities")
def facilities():
    df = pd.read_sql(text("SELECT * FROM facilities ORDER BY facility_id"),
                     analytics.engine)
    return clean(df.to_dict("records"))


@app.get("/energy/summary")
def energy_summary(facility_id: Optional[int] = None):
    check_facility(facility_id)
    df = analytics.load_energy(facility_id)
    return clean({
        "facility_id": facility_id,
        "kpis": analytics.summary(df),
        "distribution": analytics.distribution(df),
    })


@app.get("/energy/trends")
def energy_trends(facility_id: Optional[int] = None):
    check_facility(facility_id)
    df = analytics.load_energy(facility_id)
    return clean({
        "facility_id": facility_id,
        "daily": analytics.daily_trend(df),
        "hourly": analytics.hourly_profile(df),
        "weekday_vs_weekend": analytics.weekday_vs_weekend(df),
    })


@app.get("/energy/anomalies")
def energy_anomalies(
    facility_id: Optional[int] = None,
    severity: Optional[str] = Query(None, pattern="^(low|medium|high)$"),
    limit: int = Query(50, ge=1, le=500),
):
    check_facility(facility_id)
    items = anomaly.get_anomalies(facility_id)
    if severity:
        items = [a for a in items if a["severity"] == severity]
    return clean({"total": len(items), "items": items[:limit]})


@app.get("/energy/model-metrics")
def model_metrics():
    df = anomaly.detect_zscore(analytics.load_energy())
    df = anomaly.detect_isolation_forest(df)
    y = df["is_anomaly"]
    return clean({
        "rows_evaluated": len(df),
        "labeled_anomalies": int(y.sum()),
        "target_accuracy": 85,
        "zscore": anomaly.evaluate(y, df["pred_zscore"]),
        "isolation_forest": anomaly.evaluate(y, df["pred_iforest"]),
    })


@app.get("/energy/recommendations")
def energy_recommendations(facility_id: int = 1):
    check_facility(facility_id)
    sql = text("""
        SELECT title, detail, priority, est_saving_rs, source, created_at
        FROM energy_recommendations
        WHERE facility_id = :f
        ORDER BY CASE priority WHEN 'high' THEN 1
                               WHEN 'medium' THEN 2 ELSE 3 END,
                 est_saving_rs DESC
    """)
    try:
        df = pd.read_sql(sql, analytics.engine, params={"f": facility_id})
    except Exception:
        return {"items": [],
                "message": "No recommendations yet. Run the agent first."}
    message = None if len(df) else "No recommendations yet. Run the agent first."
    return clean({"items": df.to_dict("records"), "message": message})


@app.post("/energy/agent/run")
def run_agent(facility_id: int = 1):
    check_facility(facility_id)
    return clean(run_energy_agent(facility_id))
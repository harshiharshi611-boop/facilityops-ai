import os
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL) if DB_URL else None

BASE_DAYS = 10        # first 10 days of readings = the asset's own "normal"
RECENT_READINGS = 72  # last 72 hourly readings = "now"
HISTORY_DAYS = 180    # look-back window for breakdowns and repairs

WEIGHTS = {"sensor": 0.55, "age": 0.15, "maintenance": 0.15, "history": 0.15}
BANDS = [(85, "Excellent"), (70, "Good"), (50, "Warning"), (0, "Critical")]
CHANNELS = ["temperature_c", "vibration_mm_s", "current_amp"]


def status_of(score):
    for cut, name in BANDS:
        if score >= cut:
            return name
    return "Critical"


def load_tables():
    assets = pd.read_sql(
        text("SELECT * FROM assets"), engine,
        parse_dates=["install_date", "last_service_date"])
    sensors = pd.read_sql(
        text("SELECT asset_id, timestamp, temperature_c, vibration_mm_s, "
             "current_amp FROM sensor_readings"),
        engine, parse_dates=["timestamp"])
    maint = pd.read_sql(
        text("SELECT asset_id, issue_type, maintenance_type, maintenance_date, "
             "status FROM maintenance_records"),
        engine, parse_dates=["maintenance_date"])
    for c in CHANNELS:
        sensors[c] = sensors[c].astype(float)
    return assets, sensors, maint


def sensor_drift(sensors, as_of):
    s = sensors[sensors.timestamp <= as_of].copy()
    s["working"] = (s.timestamp.dt.weekday < 5) & s.timestamp.dt.hour.between(8, 19)
    first = s.groupby("asset_id").timestamp.transform("min")
    base = s[s.timestamp < first + pd.Timedelta(days=BASE_DAYS)]
    baseline = (base.groupby(["asset_id", "working"])[CHANNELS].median()
                .add_suffix("_base").reset_index())
    s = s.sort_values(["asset_id", "timestamp"])
    recent = s.groupby("asset_id").tail(RECENT_READINGS)
    recent = recent.merge(baseline, on=["asset_id", "working"], how="left")
    recent["vib_ratio"] = recent.vibration_mm_s / recent.vibration_mm_s_base
    recent["cur_ratio"] = recent.current_amp / recent.current_amp_base
    recent["temp_delta"] = recent.temperature_c - recent.temperature_c_base
    out = recent.groupby("asset_id").agg(
        vib_drift=("vib_ratio", "mean"),
        cur_drift=("cur_ratio", "mean"),
        temp_delta=("temp_delta", "mean")).reset_index()
    out["vib_drift"] -= 1
    out["cur_drift"] -= 1
    return out


def compute_health(assets, sensors, maint, as_of=None):
    if as_of is None:
        as_of = sensors.timestamp.max()
    as_of = pd.Timestamp(as_of)

    df = assets.merge(sensor_drift(sensors, as_of), on="asset_id", how="left")
    df[["vib_drift", "cur_drift", "temp_delta"]] = (
        df[["vib_drift", "cur_drift", "temp_delta"]].fillna(0))

    # 1. sensor condition (compared with the asset's own baseline)
    vib_pen = (df.vib_drift / 0.8).clip(0, 1)
    temp_pen = (df.temp_delta / 12).clip(0, 1)
    cur_pen = (df.cur_drift / 0.2).clip(0, 1)
    df["sensor_score"] = 100 * (1 - (0.5 * vib_pen + 0.3 * temp_pen + 0.2 * cur_pen))

    # 2. age against expected life
    df["age_years"] = (as_of - df.install_date).dt.days / 365.25
    df["life_used_pct"] = 100 * df.age_years / df.expected_life_years
    ratio = (df.age_years / df.expected_life_years).clip(0, 1)
    df["age_score"] = 100 * (1 - ratio ** 2)

    # 3. maintenance overdue
    df["days_since_service"] = (as_of - df.last_service_date).dt.days.clip(lower=0)
    df["days_overdue"] = (df.days_since_service - df.service_interval_days).clip(lower=0)
    overdue = (df.days_overdue / df.service_interval_days).clip(0, 1)
    df["maintenance_score"] = 100 * (1 - overdue)

    # 4. recent breakdowns and corrective repairs
    since = as_of - pd.Timedelta(days=HISTORY_DAYS)
    bad = maint[maint.maintenance_type.isin(["breakdown", "corrective"])
                & (maint.status == "completed")
                & (maint.maintenance_date > since)
                & (maint.maintenance_date <= as_of)]
    counts = bad.groupby("asset_id").size().rename("recent_failures")
    df = df.merge(counts, on="asset_id", how="left")
    df["recent_failures"] = df.recent_failures.fillna(0).astype(int)
    df["history_score"] = (100 - 50 * df.recent_failures).clip(lower=0)

    parts = {"sensor": "sensor_score", "age": "age_score",
             "maintenance": "maintenance_score", "history": "history_score"}
    df["health_score"] = sum(WEIGHTS[k] * df[c] for k, c in parts.items()).round(1)
    df["status"] = df.health_score.map(status_of)

    # biggest reason for lost points
    loss = pd.DataFrame({k: WEIGHTS[k] * (100 - df[c]) for k, c in parts.items()})
    df["main_driver"] = loss.idxmax(axis=1)

    def explain(r):
        if r.main_driver == "sensor":
            return (f"Vibration {r.vib_drift * 100:+.0f}% and temperature "
                    f"{r.temp_delta:+.1f} C vs its own baseline")
        if r.main_driver == "age":
            return f"{r.life_used_pct:.0f}% of expected life used"
        if r.main_driver == "maintenance":
            return f"Service overdue by {int(r.days_overdue)} days"
        return f"{int(r.recent_failures)} breakdown/repair in the last {HISTORY_DAYS} days"

    df["main_issue"] = df.apply(explain, axis=1)
    df["computed_at"] = as_of
    return df


# ---------------------------------------------------------------- saving
DDL = """
DROP TABLE IF EXISTS asset_health;
CREATE TABLE asset_health (
    asset_id          INT PRIMARY KEY REFERENCES assets(asset_id),
    facility_id       INT,
    asset_name        VARCHAR(100),
    asset_type        VARCHAR(50),
    criticality       INT,
    health_score      NUMERIC,
    status            VARCHAR(20),
    sensor_score      NUMERIC,
    age_score         NUMERIC,
    maintenance_score NUMERIC,
    history_score     NUMERIC,
    life_used_pct     NUMERIC,
    days_overdue      NUMERIC,
    recent_failures   INT,
    vib_drift_pct     NUMERIC,
    temp_delta_c      NUMERIC,
    cur_drift_pct     NUMERIC,
    main_issue        VARCHAR(200),
    computed_at       TIMESTAMP
);
"""


def save_health(df):
    out = df[["asset_id", "facility_id", "asset_name", "asset_type", "criticality",
              "health_score", "status", "sensor_score", "age_score",
              "maintenance_score", "history_score", "life_used_pct",
              "days_overdue", "recent_failures", "main_issue", "computed_at"]].copy()
    out["vib_drift_pct"] = (df.vib_drift * 100).round(1)
    out["temp_delta_c"] = df.temp_delta.round(2)
    out["cur_drift_pct"] = (df.cur_drift * 100).round(1)
    for c in ["sensor_score", "age_score", "maintenance_score",
              "history_score", "life_used_pct"]:
        out[c] = out[c].round(1)
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    out.to_sql("asset_health", engine, if_exists="append", index=False)


# ---------------------------------------------------------------- report
def report(df, scen, assets, sensors, maint):
    print("\nHEALTH STATUS (all assets)")
    order = ["Excellent", "Good", "Warning", "Critical"]
    counts = df.status.value_counts().reindex(order, fill_value=0)
    for name, n in counts.items():
        print(f"  {name:10s} {n:3d}  ({n / len(df) * 100:.0f}%)")

    print("\nBY FACILITY")
    print(df.groupby(["facility_id", "status"]).size()
          .unstack(fill_value=0).reindex(columns=order, fill_value=0).to_string())

    print("\nLOWEST 8 SCORES NOW")
    low = df.sort_values("health_score").head(8)
    for r in low.itertuples():
        print(f"  {r.asset_name:16s} fac {r.facility_id}  {r.health_score:5.1f}  "
              f"{r.status:9s} {r.main_issue}")

    m = df.merge(scen[["asset_id", "scenario"]], on="asset_id")
    print("\nSELF-CHECK AGAINST THE ANSWER KEY (never used for scoring)")
    print("  average score by scenario:")
    print(m.groupby("scenario").health_score.mean().round(1).to_string())
    warn = m[m.scenario == "warn"]
    blip = m[m.scenario == "blip"]
    print(f"  degrading assets flagged Warning/Critical: "
          f"{warn.status.isin(['Warning', 'Critical']).sum()} of {len(warn)}")
    print(f"  temporary-spike assets still Good/Excellent: "
          f"{blip.status.isin(['Good', 'Excellent']).sum()} of {len(blip)}")

    print("\nHEALTH BEFORE A BREAKDOWN (average of assets that later failed)")
    fails = scen[scen.scenario == "fail"].dropna(subset=["failure_time"])
    for d in [21, 14, 7, 3, 1]:
        vals = []
        for r in fails.itertuples():
            h = compute_health(assets[assets.asset_id == r.asset_id],
                               sensors[sensors.asset_id == r.asset_id],
                               maint[maint.asset_id == r.asset_id],
                               as_of=r.failure_time - pd.Timedelta(days=d))
            vals.append(h.health_score.iloc[0])
        print(f"  {d:2d} days before failure: {sum(vals) / len(vals):5.1f}")


if __name__ == "__main__":
    assets, sensors, maint = load_tables()
    df = compute_health(assets, sensors, maint)
    save_health(df)
    print("Scored", len(df), "assets and saved to table asset_health")
    scen = pd.read_sql(
        text("SELECT asset_id, scenario, failure_time FROM asset_scenarios"),
        engine, parse_dates=["failure_time"])
    report(df, scen, assets, sensors, maint)
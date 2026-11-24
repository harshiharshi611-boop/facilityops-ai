"""
occupancy.py  (Milestone 3 - Step 2)
Occupancy analytics from the database:
  1. Space utilization per zone (how full is each zone?)
  2. Overcrowding detection (count above capacity) + early "near full" warnings
  3. Heatmap data (zone x hour of day, weekday vs weekend)
  4. Facility summary
  5. Honest check against the planted answer key (occupancy_scenarios)

Saves: occupancy_zone_summary, occupancy_incidents, occupancy_heatmap,
       occupancy_facility_summary, occupancy_eval_metrics
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv(Path(__file__).resolve().parent / ".env")

FACILITY_NAMES = {1: "Tech Park Block A", 2: "City Hospital"}
THRESH_OVER = 1.00     # more people than capacity  -> overcrowding
THRESH_NEAR = 0.90     # 90% of capacity or more    -> early warning
BUSY_START, BUSY_END = 8, 19      # "busy hours" window used for utilization (weekdays)
UNDER, BUSY = 0.35, 0.75          # status bands on busy-hours utilization


# ------------------------------------------------------------------ load + check
def load(engine):
    occ = pd.read_sql("SELECT facility_id, zone, occupancy_count, timestamp FROM occupancy_records", engine)
    zones = pd.read_sql("SELECT facility_id, zone, zone_type, capacity, restricted FROM occupancy_zones", engine)
    occ["timestamp"] = pd.to_datetime(occ["timestamp"]).astype("datetime64[ns]")   # needed for PostgreSQL data
    zones["restricted"] = zones["restricted"].astype(bool)
    return occ, zones


def validate(occ, zones):
    """Simple data-quality checks. Returns a list of problems (empty = OK)."""
    problems = []
    if occ.empty:
        problems.append("occupancy_records is empty")
    if occ["occupancy_count"].isna().any():
        problems.append("missing occupancy counts")
    if (occ["occupancy_count"] < 0).any():
        problems.append("negative occupancy counts")
    known = set(zip(zones.facility_id, zones.zone))
    if not set(zip(occ.facility_id, occ.zone)) <= known:
        problems.append("records for zones not in occupancy_zones")
    return problems


def prepare(occ, zones):
    df = occ.merge(zones, on=["facility_id", "zone"], how="inner")
    df["utilization"] = df["occupancy_count"] / df["capacity"]
    df["hour"] = df["timestamp"].dt.hour
    df["is_weekend"] = df["timestamp"].dt.dayofweek >= 5
    return df


# ------------------------------------------------------------------ 1. utilization
def zone_summary(df):
    rows = []
    for (fid, zone), g in df.groupby(["facility_id", "zone"]):
        busy = g[(~g.is_weekend) & (g.hour >= BUSY_START) & (g.hour < BUSY_END)]
        wk = g[~g.is_weekend].groupby("hour")["utilization"].mean()
        busy_util = busy["utilization"].mean()
        if bool(g["restricted"].iloc[0]):
            status = "Restricted"
        elif g["zone_type"].iloc[0] == "lobby":
            status = "Transit"          # people pass through, low fill is normal
        elif busy_util < UNDER:
            status = "Underused"
        elif busy_util < BUSY:
            status = "Healthy"
        else:
            status = "Busy"
        rows.append(dict(
            facility_id=fid, zone=zone, zone_type=g["zone_type"].iloc[0], capacity=int(g["capacity"].iloc[0]),
            avg_utilization=round(g["utilization"].mean() * 100, 1),
            busy_hours_utilization=round(busy_util * 100, 1),
            peak_utilization=round(g["utilization"].max() * 100, 1),
            peak_hour=int(wk.idxmax()),
            hours_near_full=int((g["utilization"] >= THRESH_NEAR).sum()),
            hours_over_capacity=int((g["utilization"] > THRESH_OVER).sum()),
            status=status))
    out = pd.DataFrame(rows)
    out["insight"] = out.apply(insight, axis=1)
    return out


def insight(r):
    if r["status"] == "Underused":
        return (f"{r['zone']} is only {r['busy_hours_utilization']:.0f}% full in busy hours. "
                "Consider sharing it, booking it for other teams, or reducing heating/cooling there.")
    if r["status"] == "Busy":
        return (f"{r['zone']} is {r['busy_hours_utilization']:.0f}% full in busy hours. "
                "Consider staggering schedules or adding capacity.")
    if r["hours_over_capacity"] > 0:
        return (f"{r['zone']} is normally fine but went over capacity {r['hours_over_capacity']} time(s). "
                f"Check what happens around {r['peak_hour']}:00.")
    return f"{r['zone']} is used normally."


# ------------------------------------------------------------------ 2. overcrowding
def detect_incidents(df, thresh):
    """Group consecutive over-threshold hours of a zone into one incident."""
    flag = df[df["utilization"] > thresh].sort_values(["facility_id", "zone", "timestamp"]).copy()
    if flag.empty:
        return pd.DataFrame(columns=["facility_id", "zone", "start_time", "end_time", "hours",
                                     "peak_count", "capacity", "peak_utilization", "severity"])
    flag["grp"] = flag.groupby(["facility_id", "zone"])["timestamp"].transform(
        lambda s: (s.diff() > pd.Timedelta(hours=1)).cumsum())
    inc = (flag.groupby(["facility_id", "zone", "grp"])
           .agg(start_time=("timestamp", "min"), end_time=("timestamp", "max"), hours=("timestamp", "size"),
                peak_count=("occupancy_count", "max"), capacity=("capacity", "first"),
                peak_utilization=("utilization", "max"))
           .reset_index().drop(columns="grp"))
    inc["peak_utilization"] = (inc["peak_utilization"] * 100).round(1)
    inc["severity"] = np.where(inc["peak_utilization"] >= 120, "Critical",
                               np.where(inc["peak_utilization"] >= 110, "High", "Medium"))
    inc = inc.sort_values(["facility_id", "start_time"]).reset_index(drop=True)
    inc.insert(0, "incident_id", np.arange(1, len(inc) + 1))
    return inc


# ------------------------------------------------------------------ 3. heatmap
def heatmap(df):
    h = (df.assign(day_type=np.where(df.is_weekend, "Weekend", "Weekday"))
         .groupby(["facility_id", "zone", "day_type", "hour"])["utilization"].mean().reset_index())
    h["avg_utilization"] = (h.pop("utilization") * 100).round(1)
    return h


# ------------------------------------------------------------------ 4. facility summary
def facility_summary(df, zsum, inc):
    rows = []
    for fid, name in FACILITY_NAMES.items():
        z = zsum[zsum.facility_id == fid]
        g = df[(df.facility_id == fid) & (~df.restricted)]
        busy = g[(~g.is_weekend) & (g.hour >= BUSY_START) & (g.hour < BUSY_END)]
        by_zone = z[z.status != "Restricted"].sort_values("busy_hours_utilization")
        tot = g[~g.is_weekend].groupby(["timestamp"])["occupancy_count"].sum()
        peak_hour = int(tot.groupby(tot.index.hour).mean().idxmax())
        rows.append(dict(
            facility_id=fid, facility_name=name,
            occupancy_rate=round(float(busy["occupancy_count"].sum() / busy["capacity"].sum() * 100), 1),
            peak_hour=peak_hour,
            most_used_zone=by_zone.iloc[-1]["zone"], least_used_zone=by_zone.iloc[0]["zone"],
            underused_zones=int((z.status == "Underused").sum()),
            overcrowding_incidents=int((inc.facility_id == fid).sum())))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ 5. honest evaluation
def evaluate(df, occ_key, thresh):
    inc = detect_incidents(df, thresh)
    hour = pd.Timedelta(hours=1)
    # event level: was each planted event found?
    found = 0
    for _, e in occ_key.iterrows():
        w_start, w_end = e["start_time"], e["start_time"] + e["duration_hours"] * hour
        m = inc[(inc.facility_id == e["facility_id"]) & (inc.zone == e["zone"]) &
                (inc.start_time < w_end) & (inc.end_time + hour > w_start)]
        found += int(len(m) > 0)
    # incident level: how many flagged incidents are real planted ones?
    real = 0
    for _, i in inc.iterrows():
        m = occ_key[(occ_key.facility_id == i["facility_id"]) & (occ_key.zone == i["zone"]) &
                    (occ_key.start_time < i["end_time"] + hour) &
                    (occ_key.start_time + occ_key.duration_hours * hour > i["start_time"])]
        real += int(len(m) > 0)
    n_ev, n_inc = len(occ_key), len(inc)
    recall = found / n_ev if n_ev else 0.0
    precision = real / n_inc if n_inc else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return dict(threshold_pct=int(thresh * 100), planted_events=n_ev, events_found=found,
                incidents_flagged=n_inc, incidents_real=real, false_incidents=n_inc - real,
                recall_pct=round(recall * 100, 1), precision_pct=round(precision * 100, 1),
                f1_pct=round(f1 * 100, 1))


# ------------------------------------------------------------------ main
def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not found. Check backend/.env")
    engine = create_engine(url)
    occ, zones = load(engine)
    problems = validate(occ, zones)
    if problems:
        raise SystemExit("Data check failed: " + "; ".join(problems))
    print(f"Data OK: {len(occ):,} hourly records, {len(zones)} zones")

    df = prepare(occ, zones)
    zsum = zone_summary(df)
    inc = detect_incidents(df, THRESH_OVER)
    heat = heatmap(df)
    fsum = facility_summary(df, zsum, inc)

    occ_key = pd.read_sql("SELECT * FROM occupancy_scenarios", engine)
    occ_key["start_time"] = pd.to_datetime(occ_key["start_time"]).astype("datetime64[ns]")
    metrics = pd.DataFrame([evaluate(df, occ_key, THRESH_OVER), evaluate(df, occ_key, THRESH_NEAR)])

    for name, d in [("occupancy_zone_summary", zsum), ("occupancy_incidents", inc), ("occupancy_heatmap", heat),
                    ("occupancy_facility_summary", fsum), ("occupancy_eval_metrics", metrics)]:
        d.to_sql(name, engine, if_exists="replace", index=False)

    pd.set_option("display.width", 200, "display.max_columns", 20)
    print("\n=== Facility summary ===")
    print(fsum.to_string(index=False))
    print("\n=== Zone utilization (busy hours = weekdays 08:00-19:00) ===")
    print(zsum[["facility_id", "zone", "busy_hours_utilization", "peak_utilization", "peak_hour",
                "hours_near_full", "hours_over_capacity", "status"]].to_string(index=False))
    print(f"\n=== Overcrowding incidents (count > capacity): {len(inc)} ===")
    print(inc.groupby(["facility_id", "severity"]).size().unstack(fill_value=0))
    print("\n=== Check against planted answer key ===")
    print(metrics.to_string(index=False))
    print("\nSaved 5 tables. Next: occupancy_forecast.py")


if __name__ == "__main__":
    main()
import os
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL) if DB_URL else None

PLAN_DAYS = 30             # plan the next 30 days
CAPACITY_PER_DAY = 2       # planned jobs one facility's team can do per day
ROUTINE_GRACE_DAYS = 7     # a routine service may slip up to a week
RANK = {"Emergency": 0, "Urgent": 1, "Planned": 2, "Routine": 3}


def load_tables():
    assets = pd.read_sql(
        text("SELECT asset_id, facility_id, asset_name, asset_type, criticality, "
             "last_service_date, service_interval_days FROM assets"),
        engine, parse_dates=["last_service_date"])
    health = pd.read_sql(
        text("SELECT asset_id, health_score, status FROM asset_health"), engine)
    health["health_score"] = health.health_score.astype(float)
    pred = pd.read_sql(
        text("SELECT asset_id, risk_pct, risk_level, will_fail_14d, reason, predicted_at "
             "FROM failure_predictions"), engine, parse_dates=["predicted_at"])
    pred["risk_pct"] = pred.risk_pct.astype(float)
    maint = pd.read_sql(
        text("SELECT asset_id, maintenance_type, maintenance_date, status, "
             "cost_rs, downtime_hours FROM maintenance_records"),
        engine, parse_dates=["maintenance_date"])
    for c in ["cost_rs", "downtime_hours"]:
        maint[c] = maint[c].astype(float)
    return assets, health, pred, maint


def cost_benchmarks(maint):
    done = maint[maint.status == "completed"]
    bd = done[done.maintenance_type == "breakdown"]
    pv = done[done.maintenance_type == "preventive"]
    return dict(bd_cost=bd.cost_rs.mean(), pv_cost=pv.cost_rs.mean(),
                bd_down=bd.downtime_hours.mean(), pv_down=pv.downtime_hours.mean())


def action_text(reason, label, days_overdue):
    r = str(reason)
    if label in ("Emergency", "Urgent", "Planned") and not r.startswith("Behaving"):
        if r.startswith("Vibration"):
            return "Inspect bearings, alignment and lubrication"
        if r.startswith("Temperature"):
            return "Check cooling, airflow and lubrication"
        if r.startswith("Current"):
            return "Check motor, belts and electrical connections"
    if days_overdue > 0:
        return "Routine service (overdue)"
    return "Routine service"


def candidate_triggers(r, plan_start):
    """Every reason this machine might need work: (label, days until due, why)."""
    out = []
    if r.risk_pct >= 70:
        out.append(("Emergency", 0 if r.criticality >= 4 else 1,
                    f"Failure risk {r.risk_pct:.0f}% within 14 days: {r.reason}"))
    elif r.risk_pct >= 50:
        out.append(("Urgent", 5, f"Failure risk {r.risk_pct:.0f}% within 14 days: {r.reason}"))
    elif r.risk_pct >= 25:
        out.append(("Planned", 10, f"Failure risk {r.risk_pct:.0f}%: {r.reason}"))
    if r.health_score < 50:
        out.append(("Urgent", 3, f"Health score {r.health_score:.0f} (Critical)"))
    elif r.health_score < 70:
        out.append(("Planned", 10, f"Health score {r.health_score:.0f} (Warning)"))
    if r.days_overdue > 30:
        out.append(("Planned", 14, f"Service overdue by {int(r.days_overdue)} days"))
    elif r.days_overdue > 0:
        out.append(("Routine", 30, f"Service overdue by {int(r.days_overdue)} days"))
    if pd.notna(r.next_service):
        gap = max((r.next_service.normalize() - plan_start).days, 0)
        if gap <= PLAN_DAYS:
            out.append(("Routine", gap + ROUTINE_GRACE_DAYS,
                        f"Routine service due {r.next_service:%d %b}"))
    return out


def build_schedule(assets, health, pred, maint, as_of):
    as_of = pd.Timestamp(as_of)
    plan_start = as_of.normalize() + pd.Timedelta(days=1)
    bm = cost_benchmarks(maint)

    df = assets.merge(health, on="asset_id").merge(
        pred[["asset_id", "risk_pct", "risk_level", "will_fail_14d", "reason"]],
        on="asset_id")
    since = (as_of.normalize() - df.last_service_date).dt.days.clip(lower=0)
    df["days_overdue"] = (since - df.service_interval_days).clip(lower=0)
    df["due_by_interval"] = df.last_service_date + pd.to_timedelta(
        df.service_interval_days, unit="D")

    booked = (maint[(maint.status == "scheduled") & (maint.maintenance_date >= plan_start)]
              .groupby("asset_id").maintenance_date.min().rename("existing_booking"))
    df = df.merge(booked, on="asset_id", how="left")
    df["next_service"] = df[["due_by_interval", "existing_booking"]].min(axis=1)
    df.loc[df.days_overdue > 0, "next_service"] = pd.NaT   # overdue is handled above

    jobs = []
    for r in df.itertuples():
        trig = candidate_triggers(r, plan_start)
        if not trig:
            continue
        label, days, _ = min(trig, key=lambda t: (RANK[t[0]], t[1]))
        why = "; ".join(t[2] for t in trig if RANK[t[0]] <= RANK[label])
        deficit = 100 - r.health_score
        overdue_pct = min(r.days_overdue / r.service_interval_days, 1) * 100
        base = 0.6 * r.risk_pct + 0.25 * deficit + 0.15 * overdue_pct
        priority = min(100.0, base * (0.7 + 0.1 * r.criticality))
        jobs.append(dict(
            asset_id=r.asset_id, facility_id=r.facility_id, asset_name=r.asset_name,
            asset_type=r.asset_type, criticality=r.criticality,
            priority_score=round(priority, 1), priority_label=label,
            risk_pct=r.risk_pct, health_score=r.health_score,
            task=action_text(r.reason, label, r.days_overdue), reason=why,
            due_by=(plan_start + pd.Timedelta(days=days)).date(),
            existing_booking=(r.existing_booking.date()
                              if pd.notna(r.existing_booking) else None)))
    sched = pd.DataFrame(jobs)
    if sched.empty:
        return sched

    # ---- assign dates: most urgent first, spread across days ----
    usage = {}
    sched["rank"] = sched.priority_label.map(RANK)
    sched = sched.sort_values(["rank", "priority_score"], ascending=[True, False]).reset_index(drop=True)
    dates, notes = [], []
    for j in sched.itertuples():
        fac, due = j.facility_id, pd.Timestamp(j.due_by)
        note = ""
        if j.priority_label == "Emergency":
            d = plan_start
        else:
            d = None
            day = plan_start
            while day <= due:
                if day.weekday() < 5 and usage.get((fac, day), 0) < CAPACITY_PER_DAY:
                    d = day
                    break
                day += pd.Timedelta(days=1)
            if d is None:                      # window full: use least busy working day
                window = [plan_start + pd.Timedelta(days=k)
                          for k in range((due - plan_start).days + 1)]
                window = [x for x in window if x.weekday() < 5] or [plan_start]
                d = min(window, key=lambda x: usage.get((fac, x), 0))
                note = "Over capacity: team is full before the due date"
        if j.existing_booking is not None and pd.Timestamp(j.existing_booking) <= due:
            d = pd.Timestamp(j.existing_booking)
            note = "Existing booking kept"
        elif j.existing_booking is not None:
            note = f"Moved up from booking on {j.existing_booking:%d %b}"
        usage[(fac, d)] = usage.get((fac, d), 0) + 1
        dates.append(d.date())
        notes.append(note)
    sched["recommended_date"] = dates
    sched["note"] = notes

    # ---- money and downtime that acting in time could avoid ----
    frac = sched.risk_pct / 100
    risky = sched.risk_pct >= 25
    sched["potential_saving_rs"] = np.where(
        risky, (frac * (bm["bd_cost"] - bm["pv_cost"])).round(-2), 0.0)
    sched["downtime_avoided_hours"] = np.where(
        risky, (frac * (bm["bd_down"] - bm["pv_down"])).round(1), 0.0)
    sched["created_at"] = as_of
    result = sched.drop(columns=["rank"])
    result.attrs["benchmarks"] = bm
    return result


# ---------------------------------------------------------------- saving
DDL = """
DROP TABLE IF EXISTS maintenance_schedule;
CREATE TABLE maintenance_schedule (
    schedule_id            SERIAL PRIMARY KEY,
    asset_id               INT REFERENCES assets(asset_id),
    facility_id            INT,
    asset_name             VARCHAR(100),
    asset_type             VARCHAR(50),
    criticality            INT,
    priority_label         VARCHAR(10),
    priority_score         NUMERIC,
    risk_pct               NUMERIC,
    health_score           NUMERIC,
    task                   VARCHAR(100),
    reason                 VARCHAR(400),
    recommended_date       DATE,
    due_by                 DATE,
    existing_booking       DATE,
    note                   VARCHAR(100),
    potential_saving_rs    NUMERIC,
    downtime_avoided_hours NUMERIC,
    created_at             TIMESTAMP
);
"""


def save_schedule(sched):
    out = sched.copy()
    for c in ["recommended_date", "due_by", "existing_booking"]:
        out[c] = pd.to_datetime(out[c])
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    out.to_sql("maintenance_schedule", engine, if_exists="append", index=False)


# ---------------------------------------------------------------- report
def report(sched, pred):
    bm = sched.attrs["benchmarks"]
    print("\nSCHEDULE SUMMARY:", len(sched), "jobs")
    print(sched.priority_label.value_counts()
          .reindex(["Emergency", "Urgent", "Planned", "Routine"], fill_value=0).to_string())

    print("\nNEEDS ATTENTION FIRST")
    first = sched[sched.priority_label != "Routine"].sort_values(
        ["recommended_date", "priority_score"], ascending=[True, False])
    for r in first.itertuples():
        d = pd.Timestamp(r.recommended_date)
        print(f"  {d:%a %d %b}  {r.asset_name:16s} fac {r.facility_id}  "
              f"{r.priority_label:9s} priority {r.priority_score:5.1f}  {r.task}")
        if r.note:
            print(f"             note: {r.note}")
    routine = sched[sched.priority_label == "Routine"]
    if len(routine):
        d0 = pd.Timestamp(routine.recommended_date.min())
        d1 = pd.Timestamp(routine.recommended_date.max())
        print(f"  + {len(routine)} routine jobs between {d0:%d %b} and {d1:%d %b}")

    print("\nWORKLOAD (jobs per facility per day)")
    per_day = sched.groupby(["facility_id", "recommended_date"]).size()
    for fac, g in per_day.groupby(level=0):
        print(f"  facility {fac}: busiest day has {g.max()} jobs, "
              f"{(g > CAPACITY_PER_DAY).sum()} day(s) above the planned limit of {CAPACITY_PER_DAY}")
    print("  (emergency jobs and bookings that already existed can exceed the limit)")

    print("\nPOTENTIAL IMPACT OF ACTING IN TIME (jobs with failure risk of 25% or more)")
    print(f"  breakdown costs about Rs {bm['bd_cost']:,.0f} and {bm['bd_down']:.0f} h of downtime; "
          f"planned service about Rs {bm['pv_cost']:,.0f} and {bm['pv_down']:.0f} h")
    print(f"  potential cost avoided : Rs {sched.potential_saving_rs.sum():,.0f}")
    print(f"  potential downtime avoided: {sched.downtime_avoided_hours.sum():.0f} hours")

    print("\nSELF-CHECKS")
    flagged = pred[pred.will_fail_14d].asset_id
    sel = sched[sched.asset_id.isin(flagged)]
    print(f"  machines predicted to fail: {len(flagged)}, scheduled as Emergency/Urgent: "
          f"{sel.priority_label.isin(['Emergency', 'Urgent']).sum()}")
    late = (pd.to_datetime(sched.recommended_date) > pd.to_datetime(sched.due_by)).sum()
    print(f"  jobs scheduled after their due date: {late}")
    wk = sched[(sched.priority_label != "Emergency")
               & (pd.to_datetime(sched.recommended_date).dt.weekday >= 5)
               & (sched.note != "Existing booking kept")]
    print(f"  new non-emergency jobs placed on a weekend: {len(wk)}")


if __name__ == "__main__":
    assets, health, pred, maint = load_tables()
    as_of = pred.predicted_at.max()
    sched = build_schedule(assets, health, pred, maint, as_of)
    save_schedule(sched)
    print("Planned from", (as_of.normalize() + pd.Timedelta(days=1)).strftime("%a %d %b %Y"),
          "| saved", len(sched), "jobs to table maintenance_schedule")
    report(sched, pred)
import os
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL) if DB_URL else None

BASE_DAYS = 10          # first 10 days of readings = the asset's own normal
SMOOTH_HOURS = 12       # average the deviation over 12 hours
THRESHOLD = 3.0         # sustained deviation score that counts as abnormal
MIN_EVENT_HOURS = 6     # ignore anything shorter than this
MERGE_GAP_HOURS = 6     # flagged hours closer than this form one event
CHANNELS = {"temperature_c": "temp", "vibration_mm_s": "vib", "current_amp": "cur"}
LABELS = {"temp": "Temperature", "vib": "Vibration", "cur": "Current"}


def load_tables():
    sensors = pd.read_sql(
        text("SELECT asset_id, timestamp, temperature_c, vibration_mm_s, "
             "current_amp FROM sensor_readings"),
        engine, parse_dates=["timestamp"])
    maint = pd.read_sql(
        text("SELECT asset_id, maintenance_type, maintenance_date, status "
             "FROM maintenance_records"),
        engine, parse_dates=["maintenance_date"])
    for c in CHANNELS:
        sensors[c] = sensors[c].astype(float)
    return sensors, maint


def score_readings(sensors):
    s = sensors.sort_values(["asset_id", "timestamp"]).reset_index(drop=True)
    s["working"] = (s.timestamp.dt.weekday < 5) & s.timestamp.dt.hour.between(8, 19)
    first = s.groupby("asset_id").timestamp.transform("min")
    base = s[s.timestamp < first + pd.Timedelta(days=BASE_DAYS)]

    keys = ["asset_id", "working"]
    med = base.groupby(keys)[list(CHANNELS)].median().add_suffix("_med")
    dev = base.join(med, on=keys)
    for c in CHANNELS:
        dev[c + "_dev"] = (dev[c] - dev[c + "_med"]).abs()
    mad = dev.groupby(keys)[[c + "_dev" for c in CHANNELS]].median()
    mad.columns = [c + "_mad" for c in CHANNELS]
    s = s.merge(med.join(mad).reset_index(), on=keys, how="left")

    for c, short in CHANNELS.items():
        scale = (1.4826 * s[c + "_mad"]).clip(lower=0.01 * s[c + "_med"].abs())
        s["z_" + short] = (s[c] - s[c + "_med"]).abs() / scale
    s["rel_vib"] = (s.vibration_mm_s / s.vibration_mm_s_med - 1) * 100
    s["rel_cur"] = (s.current_amp / s.current_amp_med - 1) * 100
    s["rel_temp"] = s.temperature_c - s.temperature_c_med

    cols = ["z_temp", "z_vib", "z_cur", "rel_vib", "rel_cur", "rel_temp"]
    # restart the smoothing after any gap (for example a breakdown), so old
    # readings from before the gap never leak into the new ones
    gap = s.groupby("asset_id").timestamp.diff() > pd.Timedelta(hours=3)
    s["seg"] = gap.groupby(s.asset_id).cumsum()
    smooth = (s.groupby(["asset_id", "seg"])[cols]
              .transform(lambda x: x.rolling(SMOOTH_HOURS, min_periods=SMOOTH_HOURS // 2).mean()))
    s[cols] = smooth.fillna(0)
    z = s[["z_temp", "z_vib", "z_cur"]]
    s["score"] = z.max(axis=1)
    s["channel"] = z.idxmax(axis=1).str.replace("z_", "", regex=False)
    s["abnormal"] = s.score >= THRESHOLD
    return s


def severity_of(score):
    if score >= 25:
        return "high"
    if score >= 10:
        return "medium"
    return "low"


def build_events(s, maint):
    as_of = s.timestamp.max()
    breakdowns = maint[(maint.maintenance_type == "breakdown")]
    events = []
    flagged = s[s.abnormal]
    for aid, g in flagged.groupby("asset_id"):
        gap = g.timestamp.diff() > pd.Timedelta(hours=MERGE_GAP_HOURS)
        ev_id = gap.cumsum()
        for _, e in g.groupby(ev_id):
            start, end = e.timestamp.min(), e.timestamp.max()
            hours = int((end - start) / pd.Timedelta(hours=1)) + 1
            if hours < MIN_EVENT_HOURS:
                continue
            peak = e.loc[e.score.idxmax()]
            ch = peak.channel
            if ch == "vib":
                detail = f"Vibration {peak.rel_vib:+.0f}% vs its own normal"
            elif ch == "cur":
                detail = f"Current {peak.rel_cur:+.0f}% vs its own normal"
            else:
                detail = f"Temperature {peak.rel_temp:+.1f} C vs its own normal"
            b = breakdowns[(breakdowns.asset_id == aid)
                           & (breakdowns.maintenance_date >= start.normalize())
                           & (breakdowns.maintenance_date <= end.normalize() + pd.Timedelta(days=2))]
            if len(b):
                etype = "Breakdown"
            elif end >= as_of - pd.Timedelta(hours=MERGE_GAP_HOURS):
                etype = "Ongoing"
            else:
                etype = "Transient"
            events.append(dict(
                asset_id=int(aid), start_time=start, end_time=end,
                duration_hours=hours, peak_score=round(float(peak.score), 1),
                severity=severity_of(peak.score), main_channel=LABELS[ch],
                event_type=etype, message=detail))
    return pd.DataFrame(events)


# ---------------------------------------------------------------- saving
DDL = """
DROP TABLE IF EXISTS equipment_events;
CREATE TABLE equipment_events (
    event_id       SERIAL PRIMARY KEY,
    asset_id       INT REFERENCES assets(asset_id),
    start_time     TIMESTAMP,
    end_time       TIMESTAMP,
    duration_hours INT,
    peak_score     NUMERIC,
    severity       VARCHAR(10),
    main_channel   VARCHAR(20),
    event_type     VARCHAR(20),
    message        VARCHAR(200)
);
"""


def save_events(ev):
    with engine.begin() as conn:
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    if len(ev):
        ev.to_sql("equipment_events", engine, if_exists="append", index=False)


# ---------------------------------------------------------------- report
def evaluate(s, maint, scen, threshold):
    s = s.copy()
    s["abnormal"] = s.score >= threshold
    ev = build_events(s, maint)
    if not len(ev):
        return dict(threshold=threshold, caught=0, lead=float("nan"), false_assets=0)
    ev = ev.merge(scen[["asset_id", "scenario", "failure_time"]], on="asset_id")
    fails = ev[(ev.scenario == "fail") & (ev.event_type == "Breakdown")]
    first = fails.sort_values("start_time").groupby("asset_id").first()
    lead = ((first.failure_time - first.start_time) / pd.Timedelta(days=1)).mean()
    false_assets = ev[ev.scenario == "healthy"].asset_id.nunique()
    return dict(threshold=threshold, caught=len(first), lead=lead,
                false_assets=false_assets)


def report(s, ev, assets, scen, maint, health=None):
    info = assets[["asset_id", "asset_name", "facility_id"]]
    ev = ev.merge(info, on="asset_id")

    print("\nEVENTS FOUND:", len(ev))
    print(ev.groupby("event_type").size().to_string())
    print("\nBY SEVERITY")
    print(ev.groupby("severity").size().to_string())

    print("\nACTIVE ALERTS NOW (still abnormal at the latest reading)")
    active = ev[ev.event_type == "Ongoing"].sort_values("peak_score", ascending=False)
    if health is not None:
        active = active.merge(health[["asset_id", "health_score", "status"]],
                              on="asset_id", how="left")
    for r in active.itertuples():
        extra = (f"  health {r.health_score:.0f} ({r.status})"
                 if health is not None else "")
        print(f"  {r.asset_name:16s} fac {r.facility_id}  {r.severity:6s} "
              f"since {r.start_time:%d %b %H:%M}  {r.message}{extra}")

    m = ev.merge(scen[["asset_id", "scenario", "failure_time"]], on="asset_id")
    fails = m[(m.scenario == "fail") & (m.event_type == "Breakdown")]
    first = fails.sort_values("start_time").groupby("asset_id").first()
    lead = (first.failure_time - first.start_time) / pd.Timedelta(days=1)
    print("\nSELF-CHECK AGAINST THE ANSWER KEY (never used for detection)")
    print(f"  assets that later broke down and were warned first: "
          f"{len(first)} of {(scen.scenario == 'fail').sum()}")
    if len(first):
        print(f"  warning lead time before breakdown: average {lead.mean():.1f} days "
              f"(shortest {lead.min():.1f}, longest {lead.max():.1f})")
    print(f"  false alarms on healthy assets: "
          f"{m[m.scenario == 'healthy'].asset_id.nunique()} assets")
    print(f"  temporary spikes caught as Transient: "
          f"{(m[m.scenario == 'blip'].event_type == 'Transient').sum()} of "
          f"{(scen.scenario == 'blip').sum()}")
    print(f"  degrading assets raised as Ongoing: "
          f"{(m[m.scenario == 'warn'].event_type == 'Ongoing').sum()} of "
          f"{(scen.scenario == 'warn').sum()}")

    print("\nTHRESHOLD SENSITIVITY")
    for th in [2, 3, 4, 6]:
        r = evaluate(s, maint, scen, th)
        print(f"  threshold {th}: caught {r['caught']} of 10, "
              f"average lead {r['lead']:.1f} days, healthy assets falsely flagged {r['false_assets']}")


if __name__ == "__main__":
    sensors, maint = load_tables()
    s = score_readings(sensors)
    ev = build_events(s, maint)
    save_events(ev)
    print("Scored", len(s), "readings, saved", len(ev), "events to table equipment_events")
    assets = pd.read_sql(text("SELECT asset_id, asset_name, facility_id FROM assets"), engine)
    scen = pd.read_sql(
        text("SELECT asset_id, scenario, failure_time FROM asset_scenarios"),
        engine, parse_dates=["failure_time"])
    try:
        health = pd.read_sql(
            text("SELECT asset_id, health_score, status FROM asset_health"), engine)
        health["health_score"] = health.health_score.astype(float)
    except Exception:
        health = None
    report(s, ev, assets, scen, maint, health)
"""
security.py  (Milestone 3 - Step 4)
Security detection from access logs, CCTV events and visitor records.

RULES (first version written before grading; 3 small fixes were made after the
first grading run - see the notes in the README):
  1. repeated_denied       : 4 or more DENIED swipes, same badge, same door, within 10 minutes of each other
  2. off_hours_restricted  : restricted room opened while the badge was OUTSIDE the building
                             (last Main Lobby record of that badge, at or before that moment, is OUT or missing)
  3. impossible_travel     : same badge used at two different facilities within 30 minutes
  4. door_forced           : CCTV says door forced AND no badge swipe at that door within +/-2 minutes
  5. tailgating            : CCTV says tailgating, 2+ people, and at most 1 ENTRY swipe at the door within +/-10 seconds
  6. loitering             : CCTV loitering for 20+ minutes between 00:00 and 05:00
  7. visitor_overstay      : visitor stayed more than 10 hours
  8. visitor_no_checkout   : visitor has no check-out time
  9. visitor_restricted_zone : visitor record shows a restricted zone

Also: an Isolation Forest (unsupervised ML) on badge-day behaviour, compared with the rules.

Saves: security_events (the alert feed), security_eval_metrics, security_ml_check
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.ensemble import IsolationForest
from sqlalchemy import create_engine

load_dotenv(Path(__file__).resolve().parent / ".env")

DENIED_MIN, DENIED_WINDOW = 4, pd.Timedelta(minutes=10)
TRAVEL_WINDOW = pd.Timedelta(minutes=30)
FORCED_WINDOW = pd.Timedelta(minutes=2)
TAILGATE_WINDOW = pd.Timedelta(seconds=10)
LOITER_MIN, NIGHT_END = 20, 5
OVERSTAY_HOURS = 10
MATCH_WINDOW = pd.Timedelta(minutes=10)      # used only when grading
COLS = ["facility_id", "event_type", "severity", "timestamp", "zone", "badge_id", "source", "description"]


def ev(df, **fixed):
    out = df.copy()
    for k, v in fixed.items():
        out[k] = v
    return out[COLS] if len(out) else pd.DataFrame(columns=COLS)


# ------------------------------------------------------------------ load + check
def load(engine):
    a = pd.read_sql("SELECT facility_id, zone, badge_id, timestamp, direction, result FROM access_logs", engine)
    c = pd.read_sql("SELECT facility_id, zone, event_type, persons_detected, timestamp, duration_min FROM cctv_events", engine)
    v = pd.read_sql("SELECT visitor_id, facility_id, check_in, check_out, zone_visited FROM visitors", engine)
    z = pd.read_sql("SELECT facility_id, zone, restricted FROM occupancy_zones", engine)
    for d, cols in [(a, ["timestamp"]), (c, ["timestamp"]), (v, ["check_in", "check_out"])]:
        for col in cols:
            d[col] = pd.to_datetime(d[col]).astype("datetime64[ns]")      # needed for PostgreSQL data
    z["restricted"] = z["restricted"].astype(bool)
    return a, c, v, z


def validate(a, c, v):
    problems = []
    if a.empty or c.empty or v.empty:
        problems.append("access_logs, cctv_events or visitors is empty")
    if a["badge_id"].isna().any():
        problems.append("access_logs has missing badge ids")
    if a["result"].isin(["GRANTED", "DENIED"]).mean() < 1:
        problems.append("access_logs has unknown result values")
    return problems


# ------------------------------------------------------------------ rules
def rule_repeated_denied(a, restricted):
    d = a[a.result == "DENIED"].sort_values(["facility_id", "badge_id", "zone", "timestamp"]).copy()
    keys = ["facility_id", "badge_id", "zone"]
    d["grp"] = d.groupby(keys)["timestamp"].transform(lambda s: (s.diff() > DENIED_WINDOW).cumsum())
    b = d.groupby(keys + ["grp"]).agg(timestamp=("timestamp", "min"), attempts=("timestamp", "size")).reset_index()
    b = b[b.attempts >= DENIED_MIN].copy()
    is_restr = [(f, z) in restricted for f, z in zip(b.facility_id, b.zone)]
    b["severity"] = np.where(np.array(is_restr) & (b.attempts >= 6), "Critical", "High")
    b["description"] = b.apply(lambda r: f"{r.attempts} denied swipes in a row at {r.zone}", axis=1)
    return ev(b, event_type="repeated_denied", source="access_log")


def rule_off_hours_restricted(a, restricted):
    g = a[a.result == "GRANTED"]
    rest = g[[(f, z) in restricted for f, z in zip(g.facility_id, g.zone)]].sort_values("timestamp")
    lobby = g[g.zone == "Main Lobby"][["facility_id", "badge_id", "timestamp", "direction"]] \
        .rename(columns={"timestamp": "lobby_time", "direction": "last_direction"}).sort_values("lobby_time")
    m = pd.merge_asof(rest, lobby, left_on="timestamp", right_on="lobby_time",
                      by=["facility_id", "badge_id"])
    m = m[m["last_direction"] != "IN"].copy()          # last record is OUT, or no record at all
    m["severity"] = "Critical"
    m["description"] = m.apply(lambda r: f"{r.zone} opened while badge was outside the building", axis=1)
    return ev(m, event_type="off_hours_restricted", source="access_log")


def rule_impossible_travel(a):
    g = a[a.result == "GRANTED"]
    multi = g.groupby("badge_id")["facility_id"].nunique()
    sub = g[g.badge_id.isin(multi[multi > 1].index)].sort_values(["badge_id", "timestamp"]).copy()
    if sub.empty:
        return pd.DataFrame(columns=COLS)
    sub["prev_fac"] = sub.groupby("badge_id")["facility_id"].shift()
    sub["prev_ts"] = sub.groupby("badge_id")["timestamp"].shift()
    hit = sub[(sub.facility_id != sub.prev_fac) & (sub.prev_ts.notna()) &
              (sub.timestamp - sub.prev_ts <= TRAVEL_WINDOW)].copy()
    hit = hit.sort_values(["badge_id", "prev_ts"])
    first = hit.groupby("badge_id")["prev_ts"].diff().isna() | (hit.groupby("badge_id")["prev_ts"].diff() > TRAVEL_WINDOW)
    hit = hit[first].copy()                                   # one alert per incident, not one per hop
    hit["facility_id"] = hit["prev_fac"].astype(int)          # report at the first facility
    hit["timestamp"] = hit["prev_ts"]
    hit["severity"] = "Critical"
    hit["description"] = "same badge used at two facilities within 30 minutes (possible cloned badge)"
    return ev(hit, event_type="impossible_travel", source="access_log")


def rule_cctv(a, c):
    out = []
    granted = a[a.result == "GRANTED"]
    # door forced
    for _, r in c[c.event_type == "door_forced"].iterrows():
        near = granted[(granted.facility_id == r.facility_id) & (granted.zone == r.zone) &
                       ((granted.timestamp - r.timestamp).abs() <= FORCED_WINDOW)]
        if near.empty:
            out.append(dict(facility_id=r.facility_id, event_type="door_forced", severity="Critical",
                            timestamp=r.timestamp, zone=r.zone, badge_id=None, source="cctv",
                            description=f"{r.zone} door forced open, no badge swipe"))
    # tailgating
    for _, r in c[(c.event_type == "tailgating") & (c.persons_detected >= 2)].iterrows():
        near = granted[(granted.facility_id == r.facility_id) & (granted.zone == r.zone) &
                       (granted.direction == "IN") &
                       ((granted.timestamp - r.timestamp).abs() <= TAILGATE_WINDOW)]
        if len(near) <= 1:
            out.append(dict(facility_id=r.facility_id, event_type="tailgating", severity="High",
                            timestamp=r.timestamp, zone=r.zone,
                            badge_id=near.badge_id.iloc[0] if len(near) else None, source="cctv",
                            description=f"{int(r.persons_detected)} people entered {r.zone} on one swipe"))
    # loitering at night
    l = c[(c.event_type == "loitering") & (c.duration_min >= LOITER_MIN) & (c.timestamp.dt.hour < NIGHT_END)]
    for _, r in l.iterrows():
        out.append(dict(facility_id=r.facility_id, event_type="loitering", severity="Medium",
                        timestamp=r.timestamp, zone=r.zone, badge_id=None, source="cctv",
                        description=f"person stayed {int(r.duration_min)} min at {r.zone} at night"))
    return pd.DataFrame(out, columns=COLS)


def rule_visitors(v, restricted):
    out = []
    stay = (v.check_out - v.check_in).dt.total_seconds() / 3600
    for _, r in v[v.check_out.isna()].iterrows():
        out.append(dict(facility_id=r.facility_id, event_type="visitor_no_checkout", severity="Low",
                        timestamp=r.check_in, zone=r.zone_visited, badge_id=None, source="visitor",
                        description=f"visitor {r.visitor_id} has no check-out time"))
    for i, r in v[stay > OVERSTAY_HOURS].iterrows():
        out.append(dict(facility_id=r.facility_id, event_type="visitor_overstay", severity="Medium",
                        timestamp=r.check_in, zone=r.zone_visited, badge_id=None, source="visitor",
                        description=f"visitor {r.visitor_id} stayed {stay[i]:.0f} hours"))
    for _, r in v.iterrows():
        if (r.facility_id, r.zone_visited) in restricted:
            out.append(dict(facility_id=r.facility_id, event_type="visitor_restricted_zone", severity="High",
                            timestamp=r.check_in, zone=r.zone_visited, badge_id=None, source="visitor",
                            description=f"visitor {r.visitor_id} entered {r.zone_visited}"))
    return pd.DataFrame(out, columns=COLS)


# ------------------------------------------------------------------ grading
def grade(events, key):
    rows = []
    for t in sorted(key.scenario_type.unique()):
        k = key[key.scenario_type == t]
        e = events[events.event_type == t]
        tp_det, found = 0, 0
        for _, r in e.iterrows():
            m = k[(k.facility_id == r.facility_id) & ((k.start_time - r.timestamp).abs() <= MATCH_WINDOW)]
            tp_det += int(len(m) > 0)
        for _, r in k.iterrows():
            m = e[(e.facility_id == r.facility_id) & ((e.timestamp - r.start_time).abs() <= MATCH_WINDOW)]
            found += int(len(m) > 0)
        rows.append(dict(event_type=t, planted=len(k), detected=len(e), found=found, false_alarms=len(e) - tp_det,
                         recall_pct=round(100 * found / len(k), 1),
                         precision_pct=round(100 * tp_det / len(e), 1) if len(e) else 0.0))
    res = pd.DataFrame(rows)
    p, d, f, fa = res.planted.sum(), res.detected.sum(), res.found.sum(), res.false_alarms.sum()
    tp = d - fa
    rec, prec = f / p, (tp / d if d else 0.0)
    res.loc[len(res)] = dict(event_type="ALL", planted=p, detected=d, found=f, false_alarms=fa,
                             recall_pct=round(100 * rec, 1), precision_pct=round(100 * prec, 1))
    res["f1_pct"] = (2 * res.recall_pct * res.precision_pct / (res.recall_pct + res.precision_pct).replace(0, np.nan)).round(1).fillna(0.0)
    return res


# ------------------------------------------------------------------ ML comparison
def ml_badge_check(a, restricted, key, flag_share=0.005):
    """Isolation Forest on badge-day behaviour: can ML find badge problems without the rules?"""
    d = a.copy()
    d["day"] = d.timestamp.dt.floor("D")
    d["night"] = (d.timestamp.dt.hour < NIGHT_END).astype(int)
    d["denied"] = (d.result == "DENIED").astype(int)
    d["restr"] = [int(r == "GRANTED" and (f, z) in restricted) for r, f, z in zip(d.result, d.facility_id, d.zone)]
    d["restr_night"] = d.restr * d.night
    feat = d.groupby(["facility_id", "badge_id", "day"]).agg(
        swipes=("zone", "size"), denied=("denied", "sum"), night=("night", "sum"),
        restricted=("restr", "sum"), restricted_night=("restr_night", "sum"),
        zones=("zone", "nunique")).reset_index()
    cols = ["swipes", "denied", "night", "restricted", "restricted_night", "zones"]
    model = IsolationForest(n_estimators=200, contamination=flag_share, random_state=42)
    feat["flag"] = model.fit_predict(feat[cols]) == -1
    flagged = set(zip(feat[feat.flag].facility_id, feat[feat.flag].badge_id, feat[feat.flag].day))
    rows = []
    for t in ["repeated_denied", "off_hours_restricted", "impossible_travel"]:
        k = key[key.scenario_type == t]
        hit = sum((r.facility_id, r.badge_id, r.start_time.floor("D")) in flagged for _, r in k.iterrows())
        rows.append(dict(event_type=t, planted=len(k), found_by_ml=hit, recall_pct=round(100 * hit / len(k), 1)))
    return pd.DataFrame(rows), int(feat.flag.sum()), len(feat)


# ------------------------------------------------------------------ main
def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not found. Check backend/.env")
    engine = create_engine(url)
    a, c, v, z = load(engine)
    problems = validate(a, c, v)
    if problems:
        raise SystemExit("Data check failed: " + "; ".join(problems))
    print(f"Data OK: {len(a):,} badge swipes, {len(c):,} CCTV events, {len(v):,} visitors")
    restricted = set(zip(z[z.restricted].facility_id, z[z.restricted].zone))

    parts = [rule_repeated_denied(a, restricted), rule_off_hours_restricted(a, restricted),
             rule_impossible_travel(a), rule_cctv(a, c), rule_visitors(v, restricted)]
    events = pd.concat([p for p in parts if len(p)], ignore_index=True)
    events = events.sort_values(["facility_id", "timestamp"]).reset_index(drop=True)
    events.insert(0, "event_id", np.arange(1, len(events) + 1))

    key = pd.read_sql("SELECT * FROM security_scenarios", engine)
    key["start_time"] = pd.to_datetime(key["start_time"]).astype("datetime64[ns]")
    res = grade(events, key)
    ml, n_flag, n_days = ml_badge_check(a, restricted, key)

    events.to_sql("security_events", engine, if_exists="replace", index=False)
    res.to_sql("security_eval_metrics", engine, if_exists="replace", index=False)
    ml.to_sql("security_ml_check", engine, if_exists="replace", index=False)

    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(f"\n=== Security events (alerts) generated: {len(events)} ===")
    print(events.groupby(["event_type", "severity"]).size().to_string())
    print("\n=== Check against planted answer key ===")
    print(res.to_string(index=False))
    print(f"\n=== Isolation Forest (ML) on {n_days:,} badge-days, flagged {n_flag} ===")
    print(ml.to_string(index=False))
    print("\nSaved: security_events, security_eval_metrics, security_ml_check. Next: agents (Step 5)")


if __name__ == "__main__":
    main()
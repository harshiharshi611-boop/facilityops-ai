"""
generate_occupancy_security.py  (Milestone 3 - Step 1)
Creates SIMULATED occupancy + security data for 2 facilities.
Saves CSV files to ../data/m3/  (seeded, so results are repeatable).

Tables:
  occupancy_zones, occupancy_records, access_logs, cctv_events, visitors
  occupancy_scenarios, security_scenarios  -> ANSWER KEYS, used only for grading
"""
import numpy as np
import pandas as pd
from pathlib import Path

SEED = 42
START = pd.Timestamp("2026-08-01")      # same start date as Milestone 2
DAYS = 90
N_EMP = 120                              # badge holders per facility
OUT = Path(__file__).resolve().parent.parent / "data" / "m3"
rng = np.random.default_rng(SEED)

FACILITIES = {1: "Tech Park Block A", 2: "City Hospital"}
RESTRICTED = {1: "Server Room", 2: "ICU"}


def curve(points):
    """24 hourly values from (hour, value) key points."""
    xs, ys = zip(*points)
    return np.interp(np.arange(24), xs, ys)


def flat(v):
    return np.full(24, float(v))


# profile -> (weekday curve, weekend curve), values = fraction of capacity
PROFILES = {
    "office": (curve([(0, .02), (7, .03), (9, .4), (11, .8), (13, .55), (15, .8), (17, .5), (19, .1), (23, .02)]), flat(.03)),
    "meeting": (curve([(0, 0), (8, .05), (10, .6), (12, .3), (14, .65), (16, .5), (18, .05), (23, 0)]), flat(0)),
    "cafe": (curve([(0, 0), (7, .02), (8, .2), (9, .1), (12, .8), (14, .4), (16, .3), (18, .1), (20, 0), (23, 0)]), flat(.03)),
    "lobby": (curve([(0, .02), (7, .05), (9, .5), (10, .2), (13, .3), (17, .4), (19, .1), (23, .02)]), flat(.08)),
    "server": (curve([(0, .05), (9, .2), (18, .2), (23, .05)]), flat(.05)),
    "parking": (curve([(0, .05), (7, .2), (9, .75), (17, .7), (19, .3), (23, .08)]), flat(.1)),
    "training": (curve([(0, 0), (9, 0), (10, .6), (13, .1), (14, .6), (17, 0), (23, 0)]), flat(0)),
    "hlobby": (curve([(0, .05), (8, .4), (11, .7), (17, .5), (21, .1), (23, .05)]), curve([(0, .03), (9, .3), (17, .2), (23, .03)])),
    "opd": (curve([(0, .02), (8, .2), (10, .8), (12, .7), (14, .5), (17, .3), (20, .05), (23, .02)]), curve([(0, .01), (9, .3), (12, .3), (17, .1), (23, .01)])),
    "emergency": (curve([(0, .35), (6, .3), (12, .55), (18, .65), (21, .5), (23, .4)]),) * 2,
    "ward": (flat(.55),) * 2,
    "icu": (flat(.5),) * 2,
    "pharmacy": (curve([(0, .02), (8, .15), (11, .7), (17, .6), (21, .2), (23, .02)]), curve([(0, .01), (9, .3), (17, .2), (23, .01)])),
}

ZONES = [
    # facility_id, zone, zone_type, capacity, restricted, profile
    (1, "Main Lobby", "lobby", 80, False, "lobby"),
    (1, "Open Office Floor 1", "office", 160, False, "office"),
    (1, "Open Office Floor 2", "office", 160, False, "office"),
    (1, "Meeting Rooms", "meeting", 60, False, "meeting"),
    (1, "Cafeteria", "cafeteria", 120, False, "cafe"),
    (1, "Training Hall", "training", 70, False, "training"),
    (1, "Parking", "parking", 200, False, "parking"),
    (1, "Server Room", "restricted", 10, True, "server"),
    (2, "Main Lobby", "lobby", 100, False, "hlobby"),
    (2, "OPD", "clinic", 150, False, "opd"),
    (2, "Emergency", "emergency", 60, False, "emergency"),
    (2, "Ward A", "ward", 50, False, "ward"),
    (2, "Ward B", "ward", 50, False, "ward"),
    (2, "ICU", "restricted", 20, True, "icu"),
    (2, "Pharmacy", "pharmacy", 40, False, "pharmacy"),
    (2, "Parking", "parking", 180, False, "parking"),
]
ZONE_COLS = ["facility_id", "zone", "zone_type", "capacity", "restricted", "profile"]
zones_df = pd.DataFrame(ZONES, columns=ZONE_COLS)


def zrows(fid):
    return [z for z in ZONES if z[0] == fid]


# ------------------------------------------------------------------ OCCUPANCY
def gen_occupancy():
    hours = pd.date_range(START, periods=DAYS * 24, freq="h")
    hr = hours.hour.to_numpy()
    dow = hours.dayofweek.to_numpy()
    didx = (hours - START).days.to_numpy()
    recs, keys = [], []
    event_profiles = ["cafe", "meeting", "training", "opd", "emergency", "pharmacy"]
    weekdays = [d for d in range(3, DAYS - 3) if (START + pd.Timedelta(days=d)).dayofweek < 5]

    for fid in FACILITIES:
        day_factor = np.clip(rng.normal(1, 0.06, DAYS), 0.85, 1.15)
        zs = zrows(fid)
        cand = [z for z in zs if z[5] in event_profiles]
        events = {}                                   # (zone, hour_index) -> target fraction
        for _ in range(10):
            z = cand[rng.integers(len(cand))]
            wk = PROFILES[z[5]][0]
            peak = np.where(wk >= 0.5)[0]
            d = int(rng.choice(weekdays))
            h0 = int(rng.choice(peak))
            dur = int(rng.integers(1, 3))
            target = float(rng.uniform(1.08, 1.3))
            for h in range(h0, min(h0 + dur, 24)):
                events[(z[1], d * 24 + h)] = target
            keys.append(dict(facility_id=fid, zone=z[1],
                             start_time=START + pd.Timedelta(days=d, hours=h0),
                             duration_hours=dur, target_fraction=round(target, 2)))
        for z in zs:
            cap = z[3]
            wk, we = PROFILES[z[5]]
            base = np.where(dow >= 5, we[hr], wk[hr])
            lam = base * cap * day_factor[didx]
            for (zn, hi), tgt in events.items():
                if zn == z[1]:
                    lam[hi] = cap * tgt
            limit = cap if z[2] in ("ward", "restricted") else int(cap * 1.4)   # beds / rooms cannot exceed capacity
            cnt = np.clip(rng.poisson(lam), 0, limit)
            recs.append(pd.DataFrame(dict(facility_id=fid, zone=z[1],
                                          occupancy_count=cnt, timestamp=hours)))
    occ = pd.concat(recs, ignore_index=True)
    occ = occ.sort_values(["facility_id", "zone", "timestamp"]).reset_index(drop=True)
    occ.insert(0, "occupancy_id", np.arange(1, len(occ) + 1))
    return occ, pd.DataFrame(keys)


# ------------------------------------------------------------------ SECURITY
def gen_security():
    logs, scen, cctv, visitors = [], [], [], []
    employees = {}

    def add(fid, zone, badge, ts, direction="IN", result="GRANTED"):
        logs.append((fid, zone, badge, ts, direction, result, f"{zone} Door"))

    def swipe(fid, zone, badge, ts):
        if rng.random() < 0.01:                       # normal glitch: one failed swipe first
            add(fid, zone, badge, ts - pd.Timedelta(seconds=20), "IN", "DENIED")
        add(fid, zone, badge, ts)

    def key(fid, stype, badge, zone, ts, details):
        scen.append(dict(facility_id=fid, scenario_type=stype, badge_id=badge,
                         zone=zone, start_time=ts, details=details))

    def clamp(ts, lo, hi):
        return min(max(ts, lo), hi)

    def rand_weekday():
        while True:
            d = int(rng.integers(3, DAYS - 3))
            if (START + pd.Timedelta(days=d)).dayofweek < 5:
                return START + pd.Timedelta(days=d)

    def mins(m):
        return pd.Timedelta(minutes=float(m))

    # ---- employees + normal badge traffic
    for fid in FACILITIES:
        emps = []
        for i in range(1, N_EMP + 1):
            if fid == 1:
                shift = "day"
                home = str(rng.choice(["Open Office Floor 1", "Open Office Floor 2"]))
            else:
                shift = "ABC"[(i - 1) % 3]
                home = str(rng.choice(["Emergency", "Ward A", "Ward B", "OPD"]))
                if shift != "A" and home == "OPD":
                    home = "Ward A"
            emps.append(dict(badge=f"F{fid}-E{i:03d}", restricted=i <= 8, shift=shift, home=home))
        employees[fid] = emps
        lobby = "Main Lobby"
        for e in emps:
            for d in range(DAYS):
                day = START + pd.Timedelta(days=d)
                wkend = day.dayofweek >= 5
                if fid == 1:
                    if rng.random() > (0.03 if wkend else 0.9):
                        continue
                    arr = day + pd.Timedelta(hours=9) + mins(rng.normal(0, 35))
                    dep = day + pd.Timedelta(hours=18) + mins(rng.normal(0, 50))
                    dep = max(dep, arr + pd.Timedelta(hours=4))
                    swipe(fid, lobby, e["badge"], arr)
                    swipe(fid, e["home"], e["badge"], arr + mins(1))
                    swipe(fid, "Cafeteria", e["badge"],
                          clamp(day + pd.Timedelta(hours=12, minutes=30) + mins(rng.normal(0, 30)), arr, dep))
                    for _ in range(int(rng.integers(0, 3))):
                        swipe(fid, "Meeting Rooms", e["badge"],
                              clamp(day + pd.Timedelta(hours=float(rng.uniform(10, 16))), arr, dep))
                    if e["restricted"] and rng.random() < 0.3:
                        swipe(fid, "Server Room", e["badge"],
                              clamp(day + pd.Timedelta(hours=float(rng.uniform(10, 17))), arr, dep))
                else:
                    if rng.random() > 0.82:
                        continue
                    start_h = {"A": 6, "B": 14, "C": 22}[e["shift"]]
                    arr = day + pd.Timedelta(hours=start_h) + mins(rng.normal(0, 15))
                    dep = day + pd.Timedelta(hours=start_h + 8) + mins(rng.normal(0, 20))
                    swipe(fid, lobby, e["badge"], arr)
                    swipe(fid, e["home"], e["badge"], arr + mins(2))
                    if rng.random() < 0.3:
                        swipe(fid, "Pharmacy", e["badge"], arr + pd.Timedelta(hours=float(rng.uniform(1, 6))))
                    if e["restricted"] and rng.random() < 0.5:
                        swipe(fid, "ICU", e["badge"], arr + pd.Timedelta(hours=float(rng.uniform(1, 6))))
                add(fid, lobby, e["badge"], dep, "OUT", "GRANTED")

    # ---- injected badge scenarios (answer key rows)
    for fid in FACILITIES:
        emps = employees[fid]
        rz = RESTRICTED[fid]
        normal = [e for e in emps if not e["restricted"]]
        for _ in range(5):                            # repeated denied attempts
            e = normal[rng.integers(len(normal))]
            t = rand_weekday() + pd.Timedelta(hours=float(rng.uniform(8, 20)))
            n = int(rng.integers(5, 9))
            t0 = t
            for _ in range(n):
                add(fid, rz, e["badge"], t, "IN", "DENIED")
                t += pd.Timedelta(seconds=int(rng.integers(20, 90)))
            key(fid, "repeated_denied", e["badge"], rz, t0, f"{n} denied attempts at {rz}")
        pool = [e for e in emps if e["restricted"] and (fid == 1 or e["shift"] == "A")]
        for _ in range(4):                            # restricted access outside normal time
            e = pool[rng.integers(len(pool))]
            t = rand_weekday() + pd.Timedelta(hours=float(rng.uniform(0.5, 4)))
            add(fid, rz, e["badge"], t)
            key(fid, "off_hours_restricted", e["badge"], rz, t, f"{rz} opened between 00:00 and 04:00")

    for _ in range(4):                                # same badge in both facilities minutes apart
        e = employees[1][int(rng.integers(8, N_EMP))]
        t = rand_weekday() + pd.Timedelta(hours=float(rng.uniform(10, 16)))
        add(1, "Main Lobby", e["badge"], t)
        add(2, "Main Lobby", e["badge"], t + pd.Timedelta(minutes=3))
        key(1, "impossible_travel", e["badge"], "Main Lobby", t, "same badge at both facilities within 3 minutes")

    # ---- CCTV events: normal + injected
    for fid in FACILITIES:
        zs = [z for z in zrows(fid) if not z[4]]
        w = PROFILES["lobby" if fid == 1 else "hlobby"][0] + 0.05
        w = w / w.sum()
        zidx = {z[1]: i for i, z in enumerate(zrows(fid), 1)}

        def cam(zone):
            return f"CAM-{fid}-{zidx[zone]:02d}"

        for d in range(DAYS):
            day = START + pd.Timedelta(days=d)
            for _ in range(int(rng.poisson(25))):
                h = int(rng.choice(24, p=w))
                ts = day + pd.Timedelta(hours=h, minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(0, 60)))
                zone = zs[rng.integers(len(zs))][1]
                et = "motion" if rng.random() < 0.55 else "person_detected"
                cctv.append((fid, zone, cam(zone), et, 0 if et == "motion" else int(rng.integers(1, 4)),
                             round(float(rng.uniform(0.7, 0.99)), 2), ts, 0))
        every = [z[1] for z in zrows(fid)]
        for _ in range(4):                            # forced door at night
            zone = every[rng.integers(len(every))]
            t = rand_weekday() + pd.Timedelta(hours=float(rng.uniform(0, 5)))
            cctv.append((fid, zone, cam(zone), "door_forced", 1, round(float(rng.uniform(0.8, 0.97)), 2), t, 0))
            key(fid, "door_forced", None, zone, t, "door forced open, no badge swipe")
        for _ in range(6):                            # tailgating: 1 swipe, 2 people
            t = rand_weekday() + pd.Timedelta(hours=float(rng.choice([8.5, 9, 17.5, 18])))
            e = employees[fid][int(rng.integers(8, N_EMP))]
            add(fid, "Main Lobby", e["badge"], t - pd.Timedelta(seconds=2))
            cctv.append((fid, "Main Lobby", cam("Main Lobby"), "tailgating", 2, round(float(rng.uniform(0.8, 0.97)), 2), t, 0))
            key(fid, "tailgating", e["badge"], "Main Lobby", t, "2 people entered on 1 swipe")
        for _ in range(5):                            # loitering at night
            zone = ["Parking", "Main Lobby"][int(rng.integers(0, 2))]
            t = rand_weekday() + pd.Timedelta(hours=float(rng.uniform(0, 4)))
            dur = int(rng.integers(20, 61))
            cctv.append((fid, zone, cam(zone), "loitering", 1, round(float(rng.uniform(0.75, 0.95)), 2), t, dur))
            key(fid, "loitering", None, zone, t, f"person stayed {dur} min at night")

    # ---- visitors
    vn = 0
    for fid in FACILITIES:
        vz = ["Main Lobby", "Meeting Rooms", "Cafeteria", "Training Hall"] if fid == 1 else \
             ["Main Lobby", "OPD", "Ward A", "Ward B", "Pharmacy"]
        hosts = [e["badge"] for e in employees[fid] if not e["restricted"]]

        def visit(ci, hours_stay, zone, checkout=True):
            nonlocal vn
            vn += 1
            visitors.append(dict(visitor_id=f"V{vn:05d}", facility_id=fid, visitor_name=f"Visitor {vn}",
                                 host_badge=hosts[rng.integers(len(hosts))],
                                 purpose=str(rng.choice(["Meeting", "Delivery", "Interview", "Vendor", "Patient visit"])),
                                 check_in=ci,
                                 check_out=(ci + pd.Timedelta(hours=hours_stay)) if checkout else pd.NaT,
                                 zone_visited=zone))
            return vn

        for d in range(DAYS):
            day = START + pd.Timedelta(days=d)
            if day.dayofweek >= 5:
                continue
            for _ in range(int(rng.poisson(12))):
                visit(day + pd.Timedelta(hours=float(rng.uniform(9, 16))), float(rng.uniform(0.5, 4)),
                      vz[rng.integers(len(vz))])
        for _ in range(4):
            ci = rand_weekday() + pd.Timedelta(hours=float(rng.uniform(9, 14)))
            visit(ci, float(rng.uniform(11, 16)), vz[0])
            key(fid, "visitor_overstay", None, vz[0], ci, f"visitor V{vn:05d} stayed over 10 hours")
        for _ in range(3):
            ci = rand_weekday() + pd.Timedelta(hours=float(rng.uniform(9, 14)))
            visit(ci, 0, vz[0], checkout=False)
            key(fid, "visitor_no_checkout", None, vz[0], ci, f"visitor V{vn:05d} never checked out")
        for _ in range(4):
            ci = rand_weekday() + pd.Timedelta(hours=float(rng.uniform(10, 15)))
            visit(ci, float(rng.uniform(0.5, 2)), RESTRICTED[fid])
            key(fid, "visitor_restricted_zone", None, RESTRICTED[fid], ci, f"visitor V{vn:05d} entered {RESTRICTED[fid]}")

    acc = pd.DataFrame(logs, columns=["facility_id", "zone", "badge_id", "timestamp", "direction", "result", "door"])
    acc = acc.sort_values(["facility_id", "timestamp"]).reset_index(drop=True)
    acc.insert(0, "log_id", np.arange(1, len(acc) + 1))
    cc = pd.DataFrame(cctv, columns=["facility_id", "zone", "camera_id", "event_type", "persons_detected",
                                     "confidence", "timestamp", "duration_min"])
    cc = cc.sort_values(["facility_id", "timestamp"]).reset_index(drop=True)
    cc.insert(0, "cctv_id", np.arange(1, len(cc) + 1))
    sc = pd.DataFrame(scen).sort_values(["facility_id", "start_time"]).reset_index(drop=True)
    sc.insert(0, "scenario_id", np.arange(1, len(sc) + 1))
    return acc, cc, pd.DataFrame(visitors), sc


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    occ, occ_key = gen_occupancy()
    occ_key.insert(0, "scenario_id", np.arange(1, len(occ_key) + 1))
    acc, cc, vis, sec_key = gen_security()
    for name, df in [("occupancy_zones", zones_df), ("occupancy_records", occ), ("occupancy_scenarios", occ_key),
                     ("access_logs", acc), ("cctv_events", cc), ("visitors", vis), ("security_scenarios", sec_key)]:
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name:22s} {len(df):>8,} rows")

    cap = occ.merge(zones_df[["facility_id", "zone", "capacity"]], on=["facility_id", "zone"])
    over = (cap.occupancy_count > cap.capacity).sum()
    print(f"\nHours over capacity: {over} (planted overcrowding events: {len(occ_key)})")
    print("Planted security scenarios:")
    print(sec_key.groupby(["scenario_type", "facility_id"]).size().unstack(fill_value=0))
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
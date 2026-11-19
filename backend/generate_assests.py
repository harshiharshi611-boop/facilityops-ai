import numpy as np
import pandas as pd

rng = np.random.default_rng(42)

START = pd.Timestamp("2026-08-01")
DAYS = 90
HOURS = pd.date_range(START, periods=DAYS * 24, freq="h")
END = START + pd.Timedelta(days=DAYS)
N = len(HOURS)
t = np.arange(N)
working = np.asarray((HOURS.weekday < 5) & (HOURS.hour >= 8) & (HOURS.hour <= 19))

SPECS = {
    "Chiller":       dict(life=20, crit=4, temp=45, vib=2.5, cur=120, loaded=True,  interval=90),
    "AHU":           dict(life=15, crit=3, temp=38, vib=2.0, cur=25,  loaded=True,  interval=120),
    "Water Pump":    dict(life=12, crit=3, temp=55, vib=3.0, cur=40,  loaded=True,  interval=120),
    "Generator":     dict(life=25, crit=5, temp=70, vib=4.0, cur=200, loaded=False, interval=90),
    "UPS":           dict(life=10, crit=5, temp=35, vib=0.5, cur=60,  loaded=False, interval=180),
    "Elevator":      dict(life=20, crit=4, temp=40, vib=1.8, cur=30,  loaded=True,  interval=90),
    "Cooling Tower": dict(life=15, crit=3, temp=32, vib=2.2, cur=35,  loaded=True,  interval=120),
    "Transformer":   dict(life=30, crit=5, temp=60, vib=0.8, cur=300, loaded=False, interval=365),
}
LAYOUT = {"Chiller": 2, "AHU": 6, "Water Pump": 5, "Generator": 2,
          "UPS": 3, "Elevator": 3, "Cooling Tower": 2, "Transformer": 1}
FACILITIES = [1, 2]
ISSUES = ["Bearing wear", "Overheating", "Refrigerant leak",
          "Belt failure", "Electrical fault", "Lubrication issue"]

# ---------- 1. assets ----------
rows, aid = [], 1
for fid in FACILITIES:
    for atype, count in LAYOUT.items():
        sp = SPECS[atype]
        for n in range(1, count + 1):
            age_years = rng.uniform(1, sp["life"] * 0.95)
            install = START - pd.Timedelta(days=int(age_years * 365))
            days_ago = int(rng.integers(5, int(sp["interval"] * 1.6)))
            last_service = max(END - pd.Timedelta(days=days_ago),
                               install + pd.Timedelta(days=30))
            rows.append(dict(
                asset_id=aid, facility_id=fid, asset_name=f"{atype} {n}",
                asset_type=atype, status="active",
                install_date=install.date(),
                expected_life_years=sp["life"], criticality=sp["crit"],
                last_service_date=last_service.date(),
                service_interval_days=sp["interval"]))
            aid += 1
assets = pd.DataFrame(rows)

# ---------- 2. choose scenarios (per facility) ----------
scen = {}
for fid in FACILITIES:
    ids = rng.permutation(assets.loc[assets.facility_id == fid, "asset_id"].values)
    for i in ids[:5]:
        scen[int(i)] = "fail"
    for i in ids[5:7]:
        scen[int(i)] = "warn"
    for i in ids[7:10]:
        scen[int(i)] = "blip"

# ---------- 3. sensor readings ----------
frames, scenario_rows, fail_info = [], [], {}
for a in assets.itertuples():
    sp = SPECS[a.asset_type]
    kind = scen.get(a.asset_id, "healthy")
    load = np.where(working, 1.0, 0.6) if sp["loaded"] else np.ones(N)

    temp = sp["temp"] + (load - 1.0) * 10 + rng.normal(0, 0.8, N)
    vib = sp["vib"] * (0.85 + 0.15 * load) + rng.normal(0, 0.06 * sp["vib"], N)
    cur = sp["cur"] * load + rng.normal(0, 0.02 * sp["cur"], N)

    s = np.zeros(N)                    # degradation severity, 0 to 1
    keep = np.ones(N, dtype=bool)      # False during breakdown downtime
    fail_time, ramp = None, None

    if kind in ("fail", "warn"):
        if kind == "fail":
            fail_hour = int(rng.integers(35 * 24, 86 * 24))
            ramp = int(rng.integers(10, 22))
            down_h = int(rng.integers(24, 73))
        else:
            fail_hour = int(rng.integers(DAYS * 24 + 3 * 24, DAYS * 24 + 12 * 24))
            ramp = 21
            down_h = 0
        p = np.clip((t - (fail_hour - ramp * 24)) / (ramp * 24), 0, 1)
        s = p ** 1.6
        if kind == "fail":
            s[t >= fail_hour] = 0                       # repaired
            keep[(t >= fail_hour) & (t < fail_hour + down_h)] = False
            fail_time = HOURS[fail_hour]
            fail_info[a.asset_id] = (fail_time, down_h)
    elif kind == "blip":
        b0 = int(rng.integers(20 * 24, 80 * 24))
        bl = int(rng.integers(24, 49))
        s[b0:b0 + bl] = 0.5 * np.sin(np.linspace(0, np.pi, bl))

    temp = temp + s * rng.uniform(12, 25)
    vib = vib * (1 + s * rng.uniform(1.5, 3.0))
    cur = cur * (1 + s * rng.uniform(0.15, 0.35))

    df = pd.DataFrame({"asset_id": a.asset_id, "timestamp": HOURS,
                       "temperature_c": temp.round(2),
                       "vibration_mm_s": vib.round(3),
                       "current_amp": cur.round(2)})
    frames.append(df[keep])
    scenario_rows.append(dict(asset_id=a.asset_id, scenario=kind,
                              failure_time=fail_time, ramp_days=ramp))

sensors = pd.concat(frames, ignore_index=True)
scenarios = pd.DataFrame(scenario_rows)
scenarios["ramp_days"] = scenarios["ramp_days"].astype("Int64")

# ---------- 4. maintenance history ----------
mrows = []

def add(asset_id, issue, mtype, date, status, cost, down):
    mrows.append(dict(asset_id=int(asset_id), issue_type=issue,
                      maintenance_type=mtype,
                      maintenance_date=pd.Timestamp(date).date(),
                      status=status, cost_rs=cost, downtime_hours=down))

for a in assets.itertuples():
    sp = SPECS[a.asset_type]
    last = pd.Timestamp(a.last_service_date)
    install = pd.Timestamp(a.install_date)
    for k in range(4):                                   # past routine services
        d = last if k == 0 else last - pd.Timedelta(
            days=sp["interval"] * k + int(rng.integers(-7, 8)))
        if d >= install + pd.Timedelta(days=10):
            add(a.asset_id, "Routine service", "preventive", d, "completed",
                int(rng.integers(3000, 15000)), int(rng.integers(2, 5)))
    if rng.random() < 0.3:                               # old repair
        d = install + pd.Timedelta(days=int(rng.integers(60, 700)))
        if d < START - pd.Timedelta(days=30):
            add(a.asset_id, str(rng.choice(ISSUES)), "corrective", d, "completed",
                int(rng.integers(15000, 90000)), int(rng.integers(6, 49)))
    if a.asset_id in fail_info:                          # the breakdowns
        ft, dh = fail_info[a.asset_id]
        add(a.asset_id, "Breakdown: " + str(rng.choice(ISSUES)), "breakdown",
            ft, "completed", int(rng.integers(40000, 200000)), dh)

for x in rng.choice(assets.asset_id.values, size=6, replace=False):
    d = END + pd.Timedelta(days=int(rng.integers(3, 25)))
    add(x, "Routine service", "preventive", d, "scheduled", None, 0)

maint = pd.DataFrame(mrows)
maint.insert(0, "maintenance_id", range(1, len(maint) + 1))

# ---------- 5. save ----------
assets.to_csv("../data/assets.csv", index=False)
sensors.to_csv("../data/sensor_readings.csv", index=False)
scenarios.to_csv("../data/asset_scenarios.csv", index=False)
maint.to_csv("../data/maintenance_records.csv", index=False)

print("Assets:", len(assets))
print("Sensor rows:", len(sensors))
print("Maintenance records:", len(maint))
print(scenarios.scenario.value_counts().to_string())
print("Breakdowns:", (maint.maintenance_type == "breakdown").sum())
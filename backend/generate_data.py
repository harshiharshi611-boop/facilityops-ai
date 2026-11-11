import numpy as np
import pandas as pd

np.random.seed(42)

facilities = pd.DataFrame([
    {"facility_id": 1, "facility_name": "Tech Park Block A",
     "facility_type": "IT Park", "location": "Bengaluru"},
    {"facility_id": 2, "facility_name": "City Hospital",
     "facility_type": "Hospital", "location": "Hyderabad"},
])

timestamps = pd.date_range("2026-08-01", periods=90 * 24, freq="h")
rows = []

for fid, scale in [(1, 1.0), (2, 1.6)]:
    for t in timestamps:
        working = t.weekday() < 5 and 8 <= t.hour <= 19
        n = lambda s: np.random.normal(0, s)
        rows.append({
            "facility_id": fid,
            "timestamp": t,
            "hvac_kwh": (60 if working else 15) * scale + n(3),
            "lighting_kwh": (25 if working else 5) * scale + n(1.5),
            "equipment_kwh": (30 if working else 10) * scale + n(2),
            "other_kwh": 8 * scale + n(0.5),
            "water_usage": (400 if working else 60) * scale + n(20),
            "is_anomaly": 0,
            "anomaly_type": "none",
        })

df = pd.DataFrame(rows)

# Inject about 5% anomalies
idx = np.random.choice(df.index, size=int(len(df) * 0.05), replace=False)
for i in idx:
    t = df.loc[i, "timestamp"]
    off_hours = not (t.weekday() < 5 and 8 <= t.hour <= 19)
    kind = np.random.choice(["night_hvac", "power_spike", "lighting_waste", "water_leak"])
    if kind == "night_hvac" and off_hours:
        df.loc[i, "hvac_kwh"] *= 3.5
    elif kind == "lighting_waste" and off_hours:
        df.loc[i, "lighting_kwh"] *= 5
    elif kind == "water_leak":
        df.loc[i, "water_usage"] *= 4
    else:
        kind = "power_spike"
        df.loc[i, "equipment_kwh"] *= 3
        df.loc[i, "hvac_kwh"] *= 1.8
    df.loc[i, "is_anomaly"] = 1
    df.loc[i, "anomaly_type"] = kind

df["electricity_usage"] = (df.hvac_kwh + df.lighting_kwh
                           + df.equipment_kwh + df.other_kwh)
df = df.round(2)

facilities.to_csv("../data/facilities.csv", index=False)
df.to_csv("../data/energy_usage.csv", index=False)
print("Rows:", len(df), "| Anomalies:", df.is_anomaly.sum())
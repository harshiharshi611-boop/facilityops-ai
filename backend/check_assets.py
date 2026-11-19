import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

def one(sql):
    return pd.read_sql(text(sql), engine).iloc[0]

fail = one("""SELECT s.asset_id, s.failure_time, a.asset_name, a.facility_id
              FROM asset_scenarios s JOIN assets a USING(asset_id)
              WHERE s.scenario = 'fail' ORDER BY s.asset_id LIMIT 1""")
healthy = one("""SELECT s.asset_id, a.asset_name, a.facility_id
                 FROM asset_scenarios s JOIN assets a USING(asset_id)
                 WHERE s.scenario = 'healthy' ORDER BY s.asset_id LIMIT 1""")

def daily(asset_id, col):
    df = pd.read_sql(
        text(f"SELECT timestamp, {col} AS v FROM sensor_readings "
             "WHERE asset_id = :i ORDER BY timestamp"),
        engine, params={"i": int(asset_id)})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    d = df.set_index("timestamp")["v"].astype(float).resample("D").mean()
    return d / d.iloc[:14].mean()          # relative to the first 14 days

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
for ax, col, title in [(axes[0], "vibration_mm_s", "Vibration"),
                       (axes[1], "temperature_c", "Temperature")]:
    ax.plot(daily(fail.asset_id, col), color="#e5484d",
            label=f"{fail.asset_name} (facility {fail.facility_id}) fails")
    ax.plot(daily(healthy.asset_id, col), color="#1f9d61",
            label=f"{healthy.asset_name} (facility {healthy.facility_id}) healthy")
    ax.axvline(pd.Timestamp(fail.failure_time), color="gray", linestyle="--")
    ax.set_title(f"{title} relative to baseline (daily average)")
    ax.legend(fontsize=8)
    ax.tick_params(axis="x", rotation=30)

os.makedirs("../docs/screenshots", exist_ok=True)
plt.tight_layout()
plt.savefig("../docs/screenshots/m2_degradation.png", dpi=150)
print("Saved docs/screenshots/m2_degradation.png")
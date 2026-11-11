import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

TARIFF = 8.0        # Rs per kWh
WATER_RATE = 0.05   # Rs per litre
CO2_FACTOR = 0.82   # kg CO2 per kWh


def load_energy(facility_id=None):
    sql = "SELECT * FROM energy_usage"
    params = {}
    if facility_id:
        sql += " WHERE facility_id = :fid"
        params = {"fid": facility_id}
    df = pd.read_sql(text(sql + " ORDER BY timestamp"), engine, params=params)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["hour"] = df["timestamp"].dt.hour
    df["is_working"] = (df["timestamp"].dt.weekday < 5) & df["hour"].between(8, 19)
    return df


def efficiency_score(df):
    work = df[df.is_working].electricity_usage.mean()
    off = df[~df.is_working].electricity_usage.mean()
    ratio = off / work                      # lower is better
    return round(max(0, min(100, 100 - 60 * ratio)), 1)


def summary(df):
    kwh = df.electricity_usage.sum()
    litres = df.water_usage.sum()
    return {
        "total_kwh": round(kwh, 1),
        "total_mwh": round(kwh / 1000, 2),
        "electricity_cost": round(kwh * TARIFF),
        "water_litres": round(litres),
        "water_cost": round(litres * WATER_RATE),
        "carbon_kg": round(kwh * CO2_FACTOR),
        "peak_demand_kw": round(df.electricity_usage.max(), 1),
        "efficiency_score": efficiency_score(df),
    }


def daily_trend(df):
    d = df.set_index("timestamp").resample("D").agg(
        {"electricity_usage": "sum", "water_usage": "sum"}).round(1)
    return d.reset_index().to_dict("records")


def hourly_profile(df):
    h = df.groupby("hour").electricity_usage.mean().round(1)
    return h.reset_index().to_dict("records")


def distribution(df):
    cols = {"HVAC": "hvac_kwh", "Lighting": "lighting_kwh",
            "Equipment": "equipment_kwh", "Other": "other_kwh"}
    totals = {k: df[v].sum() for k, v in cols.items()}
    grand = sum(totals.values())
    return [{"name": k, "kwh": round(v), "percent": round(v / grand * 100, 1)}
            for k, v in totals.items()]


def weekday_vs_weekend(df):
    df = df.assign(day_type=df.timestamp.dt.weekday.map(
        lambda d: "Weekend" if d >= 5 else "Weekday"))
    g = df.groupby("day_type").electricity_usage.mean().round(1)
    return g.to_dict()


if __name__ == "__main__":
    df = load_energy(facility_id=1)
    print("SUMMARY:", summary(df))
    print("DISTRIBUTION:", distribution(df))
    print("WEEKDAY VS WEEKEND:", weekday_vs_weekend(df))
    print("PEAK HOUR:", max(hourly_profile(df), key=lambda r: r["electricity_usage"]))
    print("DAYS OF TREND DATA:", len(daily_trend(df)))
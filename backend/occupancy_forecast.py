"""
occupancy_forecast.py  (Milestone 3 - Step 3)
Forecasts hourly occupancy for every zone, 7 days ahead.

ACCURACY DEFINITION (fixed before running):
  accuracy = 100% - WAPE, where WAPE = sum(|predicted - actual|) / sum(actual)
  (calculated on people counts, on data the model never saw).
  Second view: % of hours predicted within +/-10% of the zone capacity.
  Project target: accuracy >= 80%.

How the test is done (no cheating):
  - Train on the first 63 days. Test on the last 27 days.
  - Test is done week by week. Each forecast only uses data from at least
    7 days earlier, exactly like a real 7-day-ahead forecast.

Saves: occupancy_forecast_metrics, occupancy_forecast_zone_metrics,
       occupancy_forecast (next 7 days), models/occupancy_forecast_model.joblib
"""
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.ensemble import HistGradientBoostingRegressor
from sqlalchemy import create_engine

load_dotenv(Path(__file__).resolve().parent / ".env")

TARGET = 80.0                 # % accuracy required by the project
TRAIN_DAYS = 63               # 9 whole weeks -> test weeks line up with the 7-day horizon
HORIZON = 168                 # 7 days in hours
NEAR_FULL = 0.90
FEATURES = ["zone_code", "hour", "dow", "lag_168", "lag_336", "level", "how_mean"]
MODEL_PATH = Path(__file__).resolve().parent / "models" / "occupancy_forecast_model.joblib"


# ------------------------------------------------------------------ data
def load(engine):
    occ = pd.read_sql("SELECT facility_id, zone, occupancy_count, timestamp FROM occupancy_records", engine)
    zones = pd.read_sql("SELECT facility_id, zone, capacity FROM occupancy_zones", engine)
    occ["timestamp"] = pd.to_datetime(occ["timestamp"]).astype("datetime64[ns]")
    df = occ.merge(zones, on=["facility_id", "zone"])
    df["utilization"] = df["occupancy_count"] / df["capacity"]
    return df.sort_values(["facility_id", "zone", "timestamp"]).reset_index(drop=True), zones


def add_future(df):
    """Add the next 7 days as empty rows so lag features can be built for them."""
    parts = [df]
    last = df["timestamp"].max()
    future_ts = pd.date_range(last + pd.Timedelta(hours=1), periods=HORIZON, freq="h")
    for (fid, zone), g in df.groupby(["facility_id", "zone"]):
        parts.append(pd.DataFrame({"facility_id": fid, "zone": zone, "timestamp": future_ts,
                                   "capacity": g["capacity"].iloc[0]}))
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["facility_id", "zone", "timestamp"]).reset_index(drop=True)


def make_features(d):
    """Every feature uses data at least 168 hours (7 days) older than the hour being forecast."""
    d = d.copy()
    g = d.groupby(["facility_id", "zone"])["utilization"]
    d["lag_168"] = g.shift(168)
    d["lag_336"] = g.shift(336)
    d["level"] = g.transform(lambda s: s.shift(168).rolling(168).mean())
    d["hour"] = d["timestamp"].dt.hour
    d["dow"] = d["timestamp"].dt.dayofweek
    d["zone_key"] = d["facility_id"].astype(str) + "|" + d["zone"]
    d["zone_code"] = d["zone_key"].astype("category").cat.codes
    return d


def add_how_mean(d, fit_rows):
    """Average utilization for each zone / day-of-week / hour, learned from fit_rows only."""
    how = (fit_rows.groupby(["facility_id", "zone", "dow", "hour"])["utilization"].mean()
           .rename("how_mean").reset_index())
    return d.drop(columns=["how_mean"], errors="ignore").merge(how, on=["facility_id", "zone", "dow", "hour"], how="left")


# ------------------------------------------------------------------ metrics
def metrics(actual_u, pred_u, capacity):
    a, p = actual_u * capacity, np.clip(pred_u, 0, None) * capacity
    err = np.abs(p - a)
    return dict(accuracy_pct=round(100 * (1 - err.sum() / a.sum()), 1),
                mae_people=round(float(err.mean()), 2),
                within_10pct_capacity=round(float((err <= 0.10 * capacity).mean() * 100), 1))


def zone_metrics(t, col):
    rows = []
    for (fid, zone), g in t.groupby(["facility_id", "zone"]):
        m = metrics(g["utilization"].to_numpy(), g[col].to_numpy(), g["capacity"].to_numpy())
        rows.append(dict(facility_id=fid, zone=zone, capacity=int(g["capacity"].iloc[0]), **m))
    return pd.DataFrame(rows)


def overcrowding_check(t, col):
    """Can the forecast warn about hours that really went over capacity?"""
    actual = t["utilization"] > 1.0
    warn = t[col] >= NEAR_FULL
    tp = int((actual & warn).sum())
    return dict(real_overcrowded_hours=int(actual.sum()), warned_hours=int(warn.sum()), caught=tp,
                recall_pct=round(100 * tp / max(int(actual.sum()), 1), 1),
                precision_pct=round(100 * tp / max(int(warn.sum()), 1), 1))


# ------------------------------------------------------------------ main
def main():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not found. Check backend/.env")
    engine = create_engine(url)
    df, zones = load(engine)
    if df.empty:
        raise SystemExit("occupancy_records is empty. Run load_occupancy_security.py first.")
    start = df["timestamp"].min()
    split = start + pd.Timedelta(days=TRAIN_DAYS)
    print(f"Data: {len(df):,} rows | train until {split.date()} | test {split.date()} to {df['timestamp'].max().date()}")

    # ---- honest test: model sees only the first 63 days
    feat = make_features(df)
    train_rows = feat[feat["timestamp"] < split]
    feat = add_how_mean(feat, train_rows)
    train = feat[(feat["timestamp"] < split)].dropna(subset=FEATURES)
    test = feat[(feat["timestamp"] >= split)].dropna(subset=FEATURES).copy()

    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=6,
                                          categorical_features=[FEATURES.index("zone_code")], random_state=42)
    model.fit(train[FEATURES], train["utilization"])
    test["pred_gb"] = model.predict(test[FEATURES]).clip(0)
    test["pred_how"] = test["how_mean"]            # simple baseline: usual value for that hour of the week
    test["pred_naive"] = test["lag_168"]           # simple baseline: same hour last week

    rows = []
    for name, col in [("Gradient Boosting (ML)", "pred_gb"), ("Hour-of-week average", "pred_how"),
                      ("Same hour last week", "pred_naive")]:
        m = metrics(test["utilization"].to_numpy(), test[col].to_numpy(), test["capacity"].to_numpy())
        rows.append(dict(model=name, **m, meets_target=bool(m["accuracy_pct"] >= TARGET)))
    res = pd.DataFrame(rows)
    zm = zone_metrics(test, "pred_gb")
    zm["meets_target"] = zm["accuracy_pct"] >= TARGET
    oc = overcrowding_check(test, "pred_gb")

    # ---- final model for the real forecast: learn from ALL data
    full = make_features(add_future(df))
    known = full[full["utilization"].notna()]
    full = add_how_mean(full, known)
    known = full[full["utilization"].notna()].dropna(subset=FEATURES)
    final = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=6,
                                          categorical_features=[FEATURES.index("zone_code")], random_state=42)
    final.fit(known[FEATURES], known["utilization"])
    fut = full[full["utilization"].isna()].copy()
    fut["predicted_utilization"] = final.predict(fut[FEATURES]).clip(0)
    fut["predicted_count"] = (fut["predicted_utilization"] * fut["capacity"]).round(1)
    fut["risk"] = np.where(fut["predicted_utilization"] >= NEAR_FULL, "Near full", "Normal")
    fut["predicted_utilization"] = (fut["predicted_utilization"] * 100).round(1)
    fut_out = fut[["facility_id", "zone", "timestamp", "capacity", "predicted_count",
                   "predicted_utilization", "risk"]].reset_index(drop=True)

    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump({"model": final, "features": FEATURES}, MODEL_PATH)
    res.to_sql("occupancy_forecast_metrics", engine, if_exists="replace", index=False)
    zm.to_sql("occupancy_forecast_zone_metrics", engine, if_exists="replace", index=False)
    fut_out.to_sql("occupancy_forecast", engine, if_exists="replace", index=False)

    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(f"\nTrain rows {len(train):,} | test rows {len(test):,} (7-day-ahead, week by week)")
    print("\n=== Test accuracy (target >= 80%) ===")
    print(res.to_string(index=False))
    print("\n=== Accuracy per zone (Gradient Boosting) ===")
    print(zm.to_string(index=False))
    print(f"\nZones meeting 80%: {int(zm['meets_target'].sum())} of {len(zm)}")
    print("\n=== Can the forecast warn about overcrowding? (warn if forecast >= 90% of capacity) ===")
    print(oc)
    print(f"\n=== Forecast saved: {len(fut_out):,} rows, "
          f"{fut_out['timestamp'].min()} to {fut_out['timestamp'].max()} ===")
    print(fut_out["risk"].value_counts().to_string())
    print(f"\nModel saved to {MODEL_PATH}")


if __name__ == "__main__":
    main()
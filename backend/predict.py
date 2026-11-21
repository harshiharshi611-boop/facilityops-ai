import os
import json
import numpy as np
import pandas as pd
import joblib
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import (precision_score, recall_score, f1_score,
                             roc_auc_score, average_precision_score)
from behavior import score_readings, LABELS

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL) if DB_URL else None

HORIZON_DAYS = 14        # "will it fail within the next 14 days?"
BASELINE_DAYS = 10       # snapshots start after each machine's baseline period
THRESHOLD = 0.5          # risk at or above this = predicted failure
TEST_DAYS = 16           # the last 16 snapshot days are kept for testing
FAR_DAYS = 28            # a flag with no breakdown within 28 days is a false alarm
MODEL_PATH = "models/failure_model.joblib"

FEATURES = ["z_vib", "z_temp", "z_cur", "rel_vib", "rel_temp", "rel_cur",
            "score_max24", "score_mean72", "score_delta24", "score_delta72",
            "abn_hours7d"]


def load_tables():
    sensors = pd.read_sql(
        text("SELECT asset_id, timestamp, temperature_c, vibration_mm_s, "
             "current_amp FROM sensor_readings"),
        engine, parse_dates=["timestamp"])
    for c in ["temperature_c", "vibration_mm_s", "current_amp"]:
        sensors[c] = sensors[c].astype(float)
    maint = pd.read_sql(
        text("SELECT asset_id, maintenance_type, maintenance_date "
             "FROM maintenance_records"), engine, parse_dates=["maintenance_date"])
    assets = pd.read_sql(
        text("SELECT asset_id, facility_id, asset_name, asset_type, criticality "
             "FROM assets"), engine)
    return sensors, maint, assets


def add_features(s):
    g = s.groupby(["asset_id", "seg"])
    s["score_max24"] = g.score.transform(lambda x: x.rolling(24, min_periods=1).max())
    s["score_mean72"] = g.score.transform(lambda x: x.rolling(72, min_periods=1).mean())
    s["abn_hours7d"] = g.abnormal.transform(
        lambda x: x.astype(float).rolling(168, min_periods=1).sum())
    s["score_delta24"] = (s.score - g.score.shift(24)).fillna(0)
    s["score_delta72"] = (s.score - g.score.shift(72)).fillna(0)
    return s


def make_snapshots(s, maint):
    """One row per machine per day (at midnight), labelled from the breakdown log."""
    first = s.groupby("asset_id").timestamp.transform("min")
    snap = s[(s.timestamp.dt.hour == 0)
             & (s.timestamp >= first + pd.Timedelta(days=BASELINE_DAYS))].copy()
    snap["D"] = pd.to_datetime(snap.timestamp.dt.normalize()).dt.as_unit("ns")
    bd = (maint[maint.maintenance_type == "breakdown"]
          [["asset_id", "maintenance_date"]]
          .rename(columns={"maintenance_date": "bd"})
          .copy())
    bd["bd"] = pd.to_datetime(bd["bd"]).dt.normalize().dt.as_unit("ns")
    bd = bd.sort_values("bd")
    snap = pd.merge_asof(snap.sort_values("D"), bd, left_on="D", right_on="bd",
                         by="asset_id", direction="forward")
    snap["days_to"] = (snap.bd - snap.D).dt.days
    snap["y"] = (snap.days_to < HORIZON_DAYS).astype(int)
    # drop days whose 14-day future is not fully inside the data
    data_end = s.timestamp.max().normalize() + pd.Timedelta(days=1)
    return snap[snap.D <= data_end - pd.Timedelta(days=HORIZON_DAYS)].reset_index(drop=True)


def split_by_time(snap):
    test_start = snap.D.max() - pd.Timedelta(days=TEST_DAYS - 1)
    train = snap[snap.D < test_start - pd.Timedelta(days=HORIZON_DAYS)]   # gap = no leakage
    test = snap[snap.D >= test_start]
    return train, test, test_start


def new_forest():
    return RandomForestClassifier(
        n_estimators=300, min_samples_leaf=5, class_weight="balanced_subsample",
        random_state=42, n_jobs=-1)


def new_logreg():
    return make_pipeline(StandardScaler(),
                         LogisticRegression(class_weight="balanced", max_iter=1000))


def scores(y, pred, prob=None):
    out = dict(precision=precision_score(y, pred, zero_division=0),
               recall=recall_score(y, pred), f1=f1_score(y, pred, zero_division=0))
    if prob is not None:
        out["roc_auc"] = roc_auc_score(y, prob)
        out["pr_auc"] = average_precision_score(y, prob)
    return {k: round(float(v), 3) for k, v in out.items()}


def asset_level(test, prob, thr):
    t = test.assign(p=prob, flag=prob >= thr)
    failing = t[t.y == 1].asset_id.unique()
    leads = []
    for a in failing:
        hit = t[(t.asset_id == a) & (t.y == 1) & t.flag]
        if len(hit):
            leads.append(float(hit.days_to.iloc[0]))
    far = t.flag & (t.days_to.isna() | (t.days_to > FAR_DAYS))
    return dict(failing=len(failing), detected=len(leads),
                lead_mean=float(np.mean(leads)) if leads else float("nan"),
                false_alarm_days=int(far.sum()),
                false_alarm_assets=int(t[far].asset_id.nunique()))


def risk_level(pct):
    if pct >= 70:
        return "Critical"
    if pct >= 50:
        return "High"
    if pct >= 25:
        return "Medium"
    return "Low"


def reason_text(r):
    ch = r.channel
    if ch == "vib":
        d = f"Vibration {r.rel_vib:+.0f}% vs its own normal"
    elif ch == "cur":
        d = f"Current {r.rel_cur:+.0f}% vs its own normal"
    else:
        d = f"Temperature {r.rel_temp:+.1f} C vs its own normal"
    if r.score_delta72 > 1:
        d += ", rising over 3 days"
    return d if r.score >= 3 else "Behaving normally"


def predict_now(model, s, assets):
    latest = s.sort_values("timestamp").groupby("asset_id").tail(1).copy()
    latest["risk"] = model.predict_proba(latest[FEATURES])[:, 1]
    latest["risk_pct"] = (latest.risk * 100).round(1)
    latest["risk_level"] = latest.risk_pct.map(risk_level)
    latest["will_fail_14d"] = latest.risk >= THRESHOLD
    latest["reason"] = latest.apply(reason_text, axis=1)
    latest["predicted_at"] = latest.timestamp
    out = latest.merge(assets, on="asset_id")
    return out.sort_values("risk_pct", ascending=False)


# ---------------------------------------------------------------- saving
DDL_PRED = """
DROP TABLE IF EXISTS failure_predictions;
CREATE TABLE failure_predictions (
    asset_id      INT PRIMARY KEY REFERENCES assets(asset_id),
    facility_id   INT,
    asset_name    VARCHAR(100),
    asset_type    VARCHAR(50),
    criticality   INT,
    risk_pct      NUMERIC,
    risk_level    VARCHAR(10),
    will_fail_14d BOOLEAN,
    reason        VARCHAR(200),
    horizon_days  INT,
    predicted_at  TIMESTAMP
);
DROP TABLE IF EXISTS failure_model_metrics;
CREATE TABLE failure_model_metrics (
    metrics_id     SERIAL PRIMARY KEY,
    model_name     VARCHAR(40),
    horizon_days   INT,
    threshold      NUMERIC,
    train_rows     INT,
    test_rows      INT,
    test_failures  INT,
    detected       INT,
    precision_pct  NUMERIC,
    recall_pct     NUMERIC,
    f1_pct         NUMERIC,
    roc_auc        NUMERIC,
    avg_lead_days  NUMERIC,
    false_alarm_assets INT,
    evaluated_at   TIMESTAMP DEFAULT NOW()
);
"""


def save_predictions(pred):
    out = pred[["asset_id", "facility_id", "asset_name", "asset_type", "criticality",
                "risk_pct", "risk_level", "will_fail_14d", "reason",
                "predicted_at"]].copy()
    out["horizon_days"] = HORIZON_DAYS
    with engine.begin() as conn:
        for stmt in DDL_PRED.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    out.to_sql("failure_predictions", engine, if_exists="append", index=False)


def save_metrics(row):
    pd.DataFrame([row]).to_sql("failure_model_metrics", engine,
                               if_exists="append", index=False)


if __name__ == "__main__":
    sensors, maint, assets = load_tables()
    s = add_features(score_readings(sensors))
    snap = make_snapshots(s, maint)
    train, test, test_start = split_by_time(snap)

    print("DATASET")
    print(f"  {len(snap)} machine-days, {int(snap.y.sum())} are within {HORIZON_DAYS} days of a breakdown")
    print(f"  train: {len(train)} rows ({int(train.y.sum())} positive, "
          f"{train[train.y == 1].asset_id.nunique()} failing machines)")
    print(f"  test : {len(test)} rows ({int(test.y.sum())} positive, "
          f"{test[test.y == 1].asset_id.nunique()} failing machines), "
          f"from {test_start:%d %b} onward")

    forest = new_forest().fit(train[FEATURES], train.y)
    p_rf = forest.predict_proba(test[FEATURES])[:, 1]
    logreg = new_logreg().fit(train[FEATURES], train.y)
    p_lr = logreg.predict_proba(test[FEATURES])[:, 1]
    rule = (test.score >= 3).astype(int)

    rf_s = scores(test.y, (p_rf >= THRESHOLD).astype(int), p_rf)
    lr_s = scores(test.y, (p_lr >= THRESHOLD).astype(int), p_lr)
    ru_s = scores(test.y, rule)
    print("\nMODEL COMPARISON ON THE UNSEEN TEST PERIOD")
    print(f"  {'method':32s} precision  recall    F1")
    for name, r in [("Random Forest (chosen)", rf_s),
                    ("Logistic Regression", lr_s),
                    ("Simple rule (behavior score>=3)", ru_s)]:
        print(f"  {name:32s} {r['precision'] * 100:6.1f}%  {r['recall'] * 100:6.1f}%  {r['f1'] * 100:5.1f}%")
    print(f"  Random Forest ROC-AUC {rf_s['roc_auc']:.3f}, PR-AUC {rf_s['pr_auc']:.3f}")

    al = asset_level(test, p_rf, THRESHOLD)
    print("\nPER-MACHINE RESULT (Random Forest)")
    print(f"  failing machines warned in time: {al['detected']} of {al['failing']}")
    print(f"  average warning before breakdown: {al['lead_mean']:.1f} days")
    print(f"  false-alarm days: {al['false_alarm_days']} on {al['false_alarm_assets']} machines")

    print("\nTHRESHOLD SENSITIVITY")
    for th in [0.3, 0.5, 0.7]:
        r = scores(test.y, (p_rf >= th).astype(int))
        a = asset_level(test, p_rf, th)
        print(f"  risk >= {th:.1f}: precision {r['precision'] * 100:.0f}%, recall {r['recall'] * 100:.0f}%, "
              f"warned {a['detected']} of {a['failing']}, false-alarm days {a['false_alarm_days']}")

    imp = pd.Series(forest.feature_importances_, index=FEATURES).sort_values(ascending=False)
    print("\nTOP SIGNALS THE MODEL USES")
    for k, v in imp.head(5).items():
        print(f"  {k:15s} {v * 100:4.1f}%")

    # final model: learn from every labelled day, then predict today
    final = new_forest().fit(snap[FEATURES], snap.y)
    os.makedirs("models", exist_ok=True)
    joblib.dump({"model": final, "features": FEATURES, "horizon_days": HORIZON_DAYS},
                MODEL_PATH)
    pred = predict_now(final, s, assets)
    save_predictions(pred)
    save_metrics(dict(
        model_name="RandomForest", horizon_days=HORIZON_DAYS, threshold=THRESHOLD,
        train_rows=len(train), test_rows=len(test), test_failures=al["failing"],
        detected=al["detected"], precision_pct=round(rf_s["precision"] * 100, 1),
        recall_pct=round(rf_s["recall"] * 100, 1), f1_pct=round(rf_s["f1"] * 100, 1),
        roc_auc=rf_s["roc_auc"], avg_lead_days=round(al["lead_mean"], 1),
        false_alarm_assets=al["false_alarm_assets"]))

    print(f"\nPREDICTED TO FAIL WITHIN {HORIZON_DAYS} DAYS "
          f"({int(pred.will_fail_14d.sum())} machines)")
    for r in pred[pred.will_fail_14d].itertuples():
        print(f"  {r.asset_name:16s} fac {r.facility_id}  risk {r.risk_pct:5.1f}%  "
              f"{r.risk_level:8s} {r.reason}")
    print("\nLOWEST RISK (top of the safe list)")
    for r in pred.tail(3).itertuples():
        print(f"  {r.asset_name:16s} fac {r.facility_id}  risk {r.risk_pct:5.1f}%")
    print("\nSaved: table failure_predictions, table failure_model_metrics, file", MODEL_PATH)
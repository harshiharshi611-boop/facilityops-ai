import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (accuracy_score, precision_score,
                             recall_score, f1_score, confusion_matrix)
from analytics import load_energy

FEATURES = ["hvac_kwh", "lighting_kwh", "equipment_kwh",
            "other_kwh", "water_usage"]
Z_THRESHOLD = 4.0
CONTEXT = ["facility_id", "is_working"]

MESSAGES = {
    "hvac_kwh": "HVAC usage abnormally high",
    "lighting_kwh": "Lighting left on or excessive",
    "equipment_kwh": "Equipment power spike",
    "other_kwh": "Unusual load on other systems",
    "water_usage": "Possible water leak",
}


def robust_z(series):
    med = series.median()
    mad = (series - med).abs().median()
    scale = 1.4826 * mad
    if scale == 0:
        scale = series.std() or 1
    return (series - med) / scale


def detect_zscore(df, threshold=Z_THRESHOLD):
    df = df.copy()
    z = pd.DataFrame(index=df.index)
    for f in FEATURES:
        z[f] = df.groupby(CONTEXT)[f].transform(robust_z)
    df["max_z"] = z.abs().max(axis=1).round(2)
    df["worst_feature"] = z.abs().idxmax(axis=1)
    df["pred_zscore"] = (df["max_z"] > threshold).astype(int)
    typical = df.groupby(CONTEXT)["electricity_usage"].transform("median")
    df["excess_kwh"] = (df["electricity_usage"] - typical).clip(lower=0).round(1)
    return df


def detect_isolation_forest(df, contamination=0.05):
    df = df.copy()
    df["pred_iforest"] = 0
    for _, g in df.groupby(CONTEXT):
        model = IsolationForest(n_estimators=200,
                                contamination=contamination,
                                random_state=42)
        labels = model.fit_predict(g[FEATURES])
        df.loc[g.index, "pred_iforest"] = (labels == -1).astype(int)
    return df


def evaluate(y_true, y_pred):
    return {
        "accuracy": round(accuracy_score(y_true, y_pred) * 100, 1),
        "precision": round(precision_score(y_true, y_pred) * 100, 1),
        "recall": round(recall_score(y_true, y_pred) * 100, 1),
        "f1": round(f1_score(y_true, y_pred) * 100, 1),
    }


def get_anomalies(facility_id=None):
    df = detect_zscore(load_energy(facility_id))
    a = df[df.pred_zscore == 1].copy()
    a["severity"] = pd.cut(a.max_z, bins=[0, 10, 25, np.inf],
                           labels=["low", "medium", "high"]).astype(str)
    a["issue"] = a.worst_feature.map(MESSAGES)
    a["timestamp"] = a.timestamp.astype(str)
    cols = ["facility_id", "timestamp", "issue", "severity",
            "max_z", "excess_kwh"]
    return a.sort_values("max_z", ascending=False)[cols].to_dict("records")


if __name__ == "__main__":
    df = load_energy()
    df = detect_zscore(df)
    df = detect_isolation_forest(df)
    y = df["is_anomaly"]

    print("ROBUST Z-SCORE :", evaluate(y, df.pred_zscore))
    print("ISOLATION FOREST:", evaluate(y, df.pred_iforest))
    print("\nConfusion matrix [[TN, FP], [FN, TP]]:")
    print(confusion_matrix(y, df.pred_zscore))

    print("\nDetection rate by anomaly type (Z-score):")
    for t, g in df[df.is_anomaly == 1].groupby("anomaly_type"):
        print(f"  {t:15s} {g.pred_zscore.mean() * 100:.1f}%")

    print("\nThreshold sensitivity:")
    for th in [3, 4, 5, 6]:
        r = evaluate(y, (df.max_z > th).astype(int))
        print(f"  threshold {th}: precision {r['precision']}%, recall {r['recall']}%")

    print("\nTop 3 anomalies:", get_anomalies()[:3])
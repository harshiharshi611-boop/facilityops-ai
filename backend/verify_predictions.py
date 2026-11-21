import os
import joblib
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

n = pd.read_sql(text("SELECT COUNT(*) AS n FROM failure_predictions"), engine).n[0]
print("failure_predictions:", n, "rows")
print(pd.read_sql(text(
    "SELECT risk_level, COUNT(*) AS machines FROM failure_predictions "
    "GROUP BY risk_level ORDER BY 2 DESC"), engine).to_string(index=False))
print()
print(pd.read_sql(text(
    "SELECT asset_name, facility_id, risk_pct, risk_level, reason "
    "FROM failure_predictions WHERE will_fail_14d ORDER BY risk_pct DESC"),
    engine).to_string(index=False))
print("\nfailure_model_metrics:")
print(pd.read_sql(text("SELECT * FROM failure_model_metrics"), engine).T)

path = "models/failure_model.joblib"
bundle = joblib.load(path)
print("\nmodel file:", path, f"({os.path.getsize(path) // 1024} KB)")
print("model:", type(bundle["model"]).__name__, "| features:", len(bundle["features"]),
      "| horizon:", bundle["horizon_days"], "days")
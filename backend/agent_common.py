"""
agent_common.py  (Milestone 3 - Step 5)
Small helpers shared by the Occupancy Agent and the Security Agent:
  - database connection
  - Claude wording (optional) with a rule-based fallback
  - saving alerts (no duplicates on re-run) and logging each agent run
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect

load_dotenv(Path(__file__).resolve().parent / ".env")

SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
SAVE_COLS = ["facility_id", "agent", "alert_type", "severity", "event_time", "created_at", "title",
             "message", "recommended_action", "escalate_to", "evidence", "status", "run_id", "dedupe_key"]

SYSTEM_PROMPT = (
    "You write short alert messages for facility managers. Use ONLY the facts given. "
    "Never change numbers, names, times or zones. Do not invent causes. "
    "Write 1 or 2 plain sentences per alert."
)


def get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not found. Check backend/.env")
    return create_engine(url)


def new_run_id(agent):
    return f"{agent}-{datetime.now():%Y%m%d-%H%M%S}"


def llm_reword(alerts):
    """Ask Claude to polish the wording. Returns (messages, used_llm).
    Claude only writes words. Severity, numbers and actions are decided by rules.
    On ANY problem (no key, no credits, bad reply) the rule-based text is used."""
    fallback = [a["message"] for a in alerts]
    key = os.getenv("ANTHROPIC_API_KEY")
    if not alerts or not key or os.getenv("USE_LLM", "1") == "0":
        return fallback, False
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        payload = [{"i": i, "facts": a["facts"]} for i, a in enumerate(alerts)]
        prompt = ("Write one message per item. Reply with ONLY a JSON array of strings, "
                  "in the same order, same length.\n" + json.dumps(payload))
        resp = client.messages.create(model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"),
                                      max_tokens=2000, system=SYSTEM_PROMPT,
                                      messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        out = json.loads(raw)
        if not isinstance(out, list) or len(out) != len(alerts):
            raise ValueError("reply is not a list of the right length")
        msgs = []
        for a, t in zip(alerts, out):
            ok = (isinstance(t, str) and 10 <= len(t) <= 400 and
                  all(str(k).lower() in t.lower() for k in a["must_include"]))
            msgs.append(t.strip() if ok else a["message"])      # keep the safe text if Claude dropped a fact
        return msgs, True
    except Exception as e:
        print(f"   (Claude not used: {type(e).__name__}: {str(e)[:90]} -> rule-based wording)")
        return fallback, False


def save_alerts(engine, table, df, dry_run):
    """Insert only NEW alerts (same dedupe_key = same alert, so re-runs do not create copies)."""
    if df.empty:
        return 0, 0
    if dry_run:
        return len(df), 0
    insp = inspect(engine)
    existing, start = set(), 1
    if insp.has_table(table):
        old = pd.read_sql(f"SELECT alert_id, dedupe_key FROM {table}", engine)
        existing = set(old["dedupe_key"])
        start = int(old["alert_id"].max()) + 1 if len(old) else 1
    new = df[~df["dedupe_key"].isin(existing)].copy()
    if len(new):
        new.insert(0, "alert_id", np.arange(start, start + len(new)))
        new.to_sql(table, engine, if_exists="append", index=False)
    return len(new), len(df) - len(new)


def log_run(engine, run_id, agent, started, status, created, skipped, used_llm, notes, dry_run):
    if dry_run:
        return
    row = pd.DataFrame([dict(run_id=run_id, agent=agent, started_at=started, finished_at=datetime.now(),
                             status=status, alerts_created=created, alerts_skipped_duplicate=skipped,
                             claude_wording=bool(used_llm), notes=notes)])
    row.to_sql("m3_agent_runs", engine, if_exists="append", index=False)
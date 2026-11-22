import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8000"
failed = 0


def call(path, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
    except urllib.error.URLError as e:
        print("Cannot reach the API at", BASE, "-", e.reason)
        print("Start it first:  uvicorn main:app --reload")
        sys.exit(1)


def check(name, ok, detail=""):
    global failed
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        failed += 1


totals = {"orders": 0, "alerts": 0}
for fid in (1, 2):
    print(f"\nFacility {fid}")
    p = {"facility_id": fid}
    code, s = call("/maintenance/summary", p)
    check("summary answers", code == 200)
    k = s["kpis"]
    check("health distribution adds up to the machine count",
          sum(d["machines"] for d in s["distribution"]) == k["assets_monitored"],
          f"({k['assets_monitored']} machines)")

    code, a = call("/maintenance/assets", p)
    scores = [x["health_score"] for x in a["items"]]
    check("assets listed, lowest health first", a["total"] == k["assets_monitored"] and scores == sorted(scores))

    code, pr = call("/maintenance/predictions", {**p, "only_flagged": "true"})
    check("flagged predictions match the KPI", pr["total"] == k["predicted_failures"],
          f"({pr['total']} machines)")

    code, sc = call("/maintenance/schedule", p)
    check("schedule matches the KPI", sc["totals"]["jobs"] == k["scheduled_jobs"],
          f"({sc['totals']['jobs']} jobs)")
    check("no job is scheduled after its due date",
          all(j["recommended_date"] <= j["due_by"] for j in sc["items"]))

    code, al = call("/maintenance/alerts", p)
    check("alerts match the KPI", al["total"] == k["open_alerts"], f"({al['total']} alerts)")

    code, wo = call("/maintenance/work-orders", p)
    check("work orders match the KPI", wo["total"] == k["open_work_orders"],
          f"({wo['total']} open)")
    check("every work order has a due date and a title",
          all(w["due_date"] and w["title"] for w in wo["items"]))

    code, ev = call("/maintenance/events", {**p, "event_type": "Ongoing"})
    check("ongoing events match the KPI", ev["total"] == k["ongoing_events"],
          f"({ev['total']} ongoing)")
    totals["orders"] += wo["total"]
    totals["alerts"] += al["total"]

print("\nWhole fleet")
code, m = call("/maintenance/model-metrics")
check("model metrics available", code == 200,
      f"(precision {m.get('precision_pct')}%, recall {m.get('recall_pct')}%)" if code == 200 else m)
code, r = call("/maintenance/agent/last-run")
check("agent has run at least once", code == 200 and r["run"] is not None,
      f"(run #{r['run']['run_id']}, {r['run']['jobs']} jobs)" if r.get("run") else "")
if r.get("run"):
    check("both facilities together equal the last run",
          totals["orders"] == r["run"]["jobs"] and totals["alerts"] == r["run"]["alerts"],
          f"({totals['orders']} orders, {totals['alerts']} alerts)")
check("unknown facility gives 404", call("/maintenance/summary", {"facility_id": 99})[0] == 404)
check("bad filter gives 422", call("/maintenance/assets", {"status": "Broken"})[0] == 422)

print()
print("ALL CHECKS PASSED" if failed == 0 else f"{failed} CHECK(S) FAILED")
sys.exit(1 if failed else 0)
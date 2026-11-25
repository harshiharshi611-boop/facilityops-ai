"""
verify_api_m3.py  (Milestone 3 - Step 6)
Checks every Occupancy and Security endpoint of the RUNNING API.
Start the API first:  uvicorn main:app --reload
Then run:             python verify_api_m3.py            (or: python verify_api_m3.py http://127.0.0.1:8000)
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)


results = []


def check(name, path, test, expect_status=200):
    status, data = get(path)
    ok = status == expect_status
    note = ""
    if ok and expect_status == 200:
        try:
            ok, note = test(data)
        except Exception as e:                       # wrong shape of data
            ok, note = False, f"unexpected data: {e}"
    elif not ok:
        note = f"status {status}" + (f" ({data})" if status == 0 else "")
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name:34s} {note}")
    return data


print(f"Checking {BASE}\n")
status0, _ = get("/api/occupancy/facilities")
if status0 == 0:
    print("Cannot reach the API. Start it first in another terminal:")
    print("    cd C:\\facilityops\\backend")
    print("    uvicorn main:app --reload")
    sys.exit(1)
if status0 == 404:
    print("The API is running but the Occupancy routes are missing.")
    print("Add the 4 lines to main.py (see the Step 6 instructions) and restart uvicorn.")
    sys.exit(1)
check("occupancy: facilities", "/api/occupancy/facilities", lambda d: (len(d) == 2, f"{len(d)} facilities"))
for f in (1, 2):
    check(f"occupancy: summary (facility {f})", f"/api/occupancy/summary?facility_id={f}",
          lambda d: (d["facility"]["occupancy_rate"] > 0, f"rate {d['facility']['occupancy_rate']}%, open alerts {d['open_alerts_total']}"))
    check(f"occupancy: zones (facility {f})", f"/api/occupancy/zones?facility_id={f}", lambda d: (len(d) == 8, f"{len(d)} zones"))
    check(f"occupancy: current (facility {f})", f"/api/occupancy/current?facility_id={f}",
          lambda d: (len(d["zones"]) == 8, f"as of {d['as_of']}"))
    check(f"occupancy: heatmap (facility {f})", f"/api/occupancy/heatmap?facility_id={f}&day_type=Weekday",
          lambda d: (len(d["zones"]) == 8 and len(d["values"][0]) == 24, "8 zones x 24 hours"))
    check(f"occupancy: incidents (facility {f})", f"/api/occupancy/incidents?facility_id={f}", lambda d: (len(d) > 0, f"{len(d)} rows"))
    check(f"occupancy: alerts (facility {f})", f"/api/occupancy/alerts?facility_id={f}", lambda d: (isinstance(d, list), f"{len(d)} alerts"))
check("occupancy: forecast (Cafeteria)", "/api/occupancy/forecast?facility_id=1&zone=Cafeteria",
      lambda d: (len(d["forecast"]) == 168 and len(d["actual"]) == 168, "168 actual + 168 forecast hours"))
check("occupancy: forecast-metrics", "/api/occupancy/forecast-metrics", lambda d: (len(d["models"]) == 3 and len(d["zones"]) == 16, "3 models, 16 zones"))
for f in (1, 2):
    check(f"security: summary (facility {f})", f"/api/security/summary?facility_id={f}",
          lambda d: (d["events_total"] > 0, f"{d['events_total']} events, open alerts {d['open_alerts_total']}"))
    check(f"security: events (facility {f})", f"/api/security/events?facility_id={f}", lambda d: (len(d) > 0, f"{len(d)} rows"))
    check(f"security: event-types (facility {f})", f"/api/security/event-types?facility_id={f}", lambda d: (len(d) > 0, f"{len(d)} types"))
    check(f"security: timeline (facility {f})", f"/api/security/timeline?facility_id={f}", lambda d: (len(d) > 0, f"{len(d)} days"))
    check(f"security: alerts (facility {f})", f"/api/security/alerts?facility_id={f}", lambda d: (isinstance(d, list), f"{len(d)} alerts"))
    check(f"security: visitors (facility {f})", f"/api/security/visitors?facility_id={f}", lambda d: (d["total"] > 0, f"{d['total']} visitors, {d['flagged']} flagged"))
    check(f"security: access-stats (facility {f})", f"/api/security/access-stats?facility_id={f}", lambda d: (len(d) > 0, f"{len(d)} zones"))
ev = check("security: events (for investigate)", "/api/security/events?facility_id=1&severity=Critical", lambda d: (len(d) > 0, "found a Critical event"))
if isinstance(ev, list) and ev:
    eid = ev[0]["event_id"]
    check(f"security: investigate #{eid}", f"/api/security/investigate/{eid}", lambda d: ("event" in d and "badge_timeline" in d, "event + evidence"))
check("security: evaluation", "/api/security/evaluation", lambda d: (len(d["rules"]) == 10 and len(d["ml"]) == 3, "10 rule rows, 3 ML rows"))
check("error: unknown facility gives 404", "/api/occupancy/summary?facility_id=9", lambda d: (True, ""), expect_status=404)
check("error: unknown event gives 404", "/api/security/investigate/999999", lambda d: (True, ""), expect_status=404)
check("error: bad day_type gives 400", "/api/occupancy/heatmap?facility_id=1&day_type=Sunday", lambda d: (True, ""), expect_status=400)

print(f"\n{sum(results)} of {len(results)} checks passed")
sys.exit(0 if all(results) else 1)
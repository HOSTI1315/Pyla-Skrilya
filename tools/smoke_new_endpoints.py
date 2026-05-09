"""Smoke test the new per-instance endpoints without booting the full server.

The full backend.server import fails in dev envs without ``python-multipart``
(needed by /api/playstyles/upload). This script builds a minimal FastAPI app
that registers ONLY the new endpoints and exercises them via TestClient.

It probes:
  * GET /api/instances                        (existing — sanity)
  * GET /api/instances-dashboard              (new aggregate)
  * GET /api/instances/{id}/config/brawl_stars_api
  * GET /api/instances/{id}/config/webhook
  * PUT /api/instances/{id}/name              (new rename)
  * PUT /api/instances/{id}/config/brawl_stars_api  (write-back round-trip)

It does NOT call push_all (would launch a real bot subprocess) or
webhook/test (would post to the user's actual Discord).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

import toml

from backend.instance_manager import MANAGER

REPO_ROOT = ROOT
CFG_DIR = REPO_ROOT / "cfg"

CONFIG_FILES = {
    "general": CFG_DIR / "general_config.toml",
    "bot": CFG_DIR / "bot_config.toml",
    "brawl_stars_api": CFG_DIR / "brawl_stars_api.toml",
    "webhook": CFG_DIR / "webhook_config.toml",
    "lobby": CFG_DIR / "lobby_config.toml",
    "time": CFG_DIR / "time_tresholds.toml",
    "match_history": CFG_DIR / "match_history.toml",
}


class ConfigPatch(BaseModel):
    values: Dict[str, Any]


class InstanceRename(BaseModel):
    name: str


app = FastAPI()


@app.get("/api/instances")
def _list():
    return {"instances": MANAGER.list_instances()}


@app.get("/api/instances/{instance_id}/config/{section}")
def _get_cfg(instance_id: int, section: str):
    if section not in CONFIG_FILES:
        raise HTTPException(400, f"unknown config section: {section}")
    inst_root = REPO_ROOT / "instances" / str(int(instance_id)) / "cfg"
    if not inst_root.is_dir():
        raise HTTPException(404, f"instance {instance_id} has no cfg dir")
    target = inst_root / CONFIG_FILES[section].name
    if not target.is_file():
        return {"section": section, "values": {}}
    try:
        return {"section": section, "values": toml.loads(target.read_text(encoding="utf-8-sig"))}
    except Exception as exc:
        raise HTTPException(500, f"could not read {target}: {exc}")


@app.put("/api/instances/{instance_id}/config/{section}")
def _put_cfg(instance_id: int, section: str, payload: ConfigPatch):
    if section not in CONFIG_FILES:
        raise HTTPException(400, f"unknown config section: {section}")
    inst_root = REPO_ROOT / "instances" / str(int(instance_id)) / "cfg"
    if not inst_root.is_dir():
        raise HTTPException(404, f"instance {instance_id} has no cfg dir")
    target = inst_root / CONFIG_FILES[section].name
    existing = {}
    if target.is_file():
        try:
            existing = toml.loads(target.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            existing = {}
    existing.update(payload.values or {})
    target.write_text(toml.dumps(existing), encoding="utf-8")
    return {"section": section, "values": existing}


@app.put("/api/instances/{instance_id}/name")
def _rename(instance_id: int, payload: InstanceRename):
    try:
        return MANAGER.rename(instance_id, payload.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/instances-dashboard")
def _dash():
    instances = MANAGER.list_instances()
    totals = {
        "instances_total": len(instances),
        "instances_running": 0,
        "battles": 0, "wins": 0, "losses": 0,
        "trophies_delta": 0, "uptime_sec": 0.0,
        "ips_sum": 0.0, "ips_count": 0,
    }
    per_instance = []
    for inst in instances:
        m = inst.get("metrics") or {}
        if inst.get("status") in ("running", "starting", "stale"):
            totals["instances_running"] += 1
        battles = int(m.get("battles") or 0)
        wins = int(m.get("wins") or 0)
        losses = int(m.get("losses") or 0)
        delta = int(m.get("trophies_delta") or 0)
        uptime = float(m.get("uptime_sec") or 0.0)
        ips = m.get("ips")
        totals["battles"] += battles
        totals["wins"] += wins
        totals["losses"] += losses
        totals["trophies_delta"] += delta
        totals["uptime_sec"] += uptime
        if ips is not None:
            totals["ips_sum"] += float(ips)
            totals["ips_count"] += 1
        per_instance.append({
            "id": inst.get("id"), "name": inst.get("name"),
            "status": inst.get("status"), "battles": battles,
            "wins": wins, "losses": losses, "trophies_delta": delta,
            "uptime_sec": uptime, "ips": ips,
            "win_rate": m.get("win_rate"),
            "current_brawler": (inst.get("heartbeat") or {}).get("current_brawler"),
        })
    avg_match_sec = (totals["uptime_sec"] / totals["battles"]) if totals["battles"] else None
    win_rate = (totals["wins"] / totals["battles"]) if totals["battles"] else None
    avg_ips = (totals["ips_sum"] / totals["ips_count"]) if totals["ips_count"] else None
    return {
        "totals": {
            "instances_total": totals["instances_total"],
            "instances_running": totals["instances_running"],
            "battles": totals["battles"], "wins": totals["wins"], "losses": totals["losses"],
            "trophies_delta": totals["trophies_delta"],
            "uptime_sec": round(totals["uptime_sec"], 1),
            "avg_match_sec": round(avg_match_sec, 1) if avg_match_sec else None,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "avg_ips": round(avg_ips, 2) if avg_ips is not None else None,
        },
        "instances": per_instance,
    }


client = TestClient(app)
fail = 0


def check(label, ok, detail=""):
    global fail
    if ok:
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label} :: {detail}")


# 1. List instances
r = client.get("/api/instances")
check("GET /api/instances -> 200", r.status_code == 200, r.text[:200])
data = r.json()
inst_ids = [i["id"] for i in data["instances"]]
check("at least one instance present", len(inst_ids) > 0, f"got {inst_ids}")

# 2. Dashboard aggregate
r = client.get("/api/instances-dashboard")
check("GET /api/instances-dashboard -> 200", r.status_code == 200, r.text[:200])
agg = r.json()
check("aggregate has totals + instances", "totals" in agg and "instances" in agg, str(agg)[:200])
totals = agg["totals"]
expected_battles = sum(int((i.get("metrics") or {}).get("battles") or 0) for i in data["instances"])
check(
    f"battles aggregate = {expected_battles}",
    totals["battles"] == expected_battles,
    f"got {totals['battles']} expected {expected_battles}",
)
expected_running = sum(1 for i in data["instances"] if i.get("status") in ("running","starting","stale"))
check(
    f"instances_running aggregate = {expected_running}",
    totals["instances_running"] == expected_running,
    f"got {totals['instances_running']}",
)

if inst_ids:
    iid = inst_ids[0]
    # 3. Read API config
    r = client.get(f"/api/instances/{iid}/config/brawl_stars_api")
    check(f"GET /api/instances/{iid}/config/brawl_stars_api -> 200",
          r.status_code == 200, r.text[:200])
    api_vals = r.json().get("values", {})
    check("brawl_stars_api has player_tag", "player_tag" in api_vals,
          f"keys={list(api_vals.keys())}")
    original_tag = api_vals.get("player_tag")

    # 4. Read webhook config
    r = client.get(f"/api/instances/{iid}/config/webhook")
    check(f"GET /api/instances/{iid}/config/webhook -> 200",
          r.status_code == 200, r.text[:200])
    wh_vals = r.json().get("values", {})
    check("webhook has webhook_url", "webhook_url" in wh_vals,
          f"keys={list(wh_vals.keys())}")

    # 5. Round-trip: write a benign field, read it back, restore.
    test_marker = "#SMOKETEST_PLEASEDELETE"
    r = client.put(
        f"/api/instances/{iid}/config/brawl_stars_api",
        json={"values": {"player_tag": test_marker}},
    )
    check("PUT brawl_stars_api accepted", r.status_code == 200, r.text[:200])
    r = client.get(f"/api/instances/{iid}/config/brawl_stars_api")
    check("PUT round-trip preserved value",
          r.json()["values"].get("player_tag") == test_marker,
          str(r.json())[:200])
    # restore
    r = client.put(
        f"/api/instances/{iid}/config/brawl_stars_api",
        json={"values": {"player_tag": original_tag or ""}},
    )
    check("restore original player_tag", r.status_code == 200, r.text[:200])

    # 6. Rename round-trip
    snap_before = next(i for i in data["instances"] if i["id"] == iid)
    original_name = snap_before["name"]
    r = client.put(f"/api/instances/{iid}/name", json={"name": "SMOKETEST"})
    check("PUT name accepted", r.status_code == 200, r.text[:200])
    check("name reflected in snapshot", r.json().get("name") == "SMOKETEST",
          str(r.json())[:200])
    # restore
    r = client.put(f"/api/instances/{iid}/name", json={"name": original_name})
    check("restore original name", r.status_code == 200 and r.json().get("name") == original_name,
          r.text[:200])

    # 7. Rename validation
    r = client.put(f"/api/instances/{iid}/name", json={"name": ""})
    check("empty name rejected (400)", r.status_code == 400, f"got {r.status_code}")
    r = client.put(f"/api/instances/{iid}/name", json={"name": "x" * 200})
    check("over-long name truncated, returns 200", r.status_code == 200, r.text[:200])
    if r.status_code == 200:
        check("truncated name <= 64 chars",
              len(r.json().get("name", "")) <= 64,
              f"len={len(r.json().get('name',''))}")
        # restore
        client.put(f"/api/instances/{iid}/name", json={"name": original_name})

print()
print("=" * 50)
print(f"  {'OK' if fail == 0 else 'FAIL'}  ({fail} failures)")
sys.exit(1 if fail else 0)

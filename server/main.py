import asyncio
import os
import socket
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import alerts
import config as config_mod
import storage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "0.1.0"
START_TIME = time.time()


async def offline_loop():
    while True:
        try:
            config_mod.reload_if_changed()
            transitions = storage.check_offline(
                config_mod.CONFIG["agent_offline_after_seconds"]
            )
            for t in transitions:
                alerts.enqueue(t)
        except Exception:
            pass
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app):
    storage.init_db()
    alerts.ensure_worker()
    task = asyncio.create_task(offline_loop())
    yield
    task.cancel()


app = FastAPI(title="5agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.post("/api/heartbeat")
async def heartbeat(request: Request):
    data = await request.json()
    agent_id = data.get("agent_id")
    if not agent_id:
        return JSONResponse({"error": "no agent_id"}, status_code=400)
    devices = data.get("devices") or []
    local_ip = data.get("local_ip", "") or ""
    remote_ip = ""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        remote_ip = xff.split(",")[0].strip()
    elif request.client:
        remote_ip = request.client.host or ""
    code, transitions = storage.process_heartbeat(
        agent_id, data.get("hostname", ""), data.get("ts"), devices,
        auto_approve=config_mod.CONFIG.get("auto_approve_agents", True),
        local_ip=local_ip, remote_ip=remote_ip,
    )
    if code == "disabled":
        return JSONResponse({
            "ok": False, "reason": "disabled",
            "short_id": storage.get_agent_short_id(agent_id),
        }, status_code=403)
    short_id = storage.get_agent_short_id(agent_id)
    if code == "ok":
        for t in transitions:
            alerts.enqueue(t)
        return {"ok": True, "state": "active", "short_id": short_id}
    return {"ok": True, "state": "pending", "short_id": short_id}


@app.post("/api/agents/{agent_id}/enable")
async def enable_agent(agent_id: str):
    storage.set_agent_state(agent_id, "active")
    return {"ok": True}


@app.post("/api/agents/{agent_id}/disable")
async def disable_agent(agent_id: str):
    storage.set_agent_state(agent_id, "disabled")
    return {"ok": True}


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    storage.delete_agent(agent_id)
    return {"ok": True}


@app.post("/api/agents/{agent_id}/rename")
async def rename_agent(agent_id: str, request: Request):
    data = await request.json()
    storage.rename_agent(agent_id, data.get("name", ""))
    return {"ok": True}


@app.post("/api/devices/{agent_id}/{device_id}/rename")
async def rename_device(agent_id: str, device_id: str, request: Request):
    data = await request.json()
    storage.rename_device(agent_id, device_id, data.get("name", ""))
    return {"ok": True}


@app.post("/api/agents/{agent_id}/group")
async def set_agent_group(agent_id: str, request: Request):
    data = await request.json()
    storage.assign_agent_group(agent_id, data.get("group_id") or None)
    return {"ok": True}


@app.post("/api/zones")
async def create_zone(request: Request):
    data = await request.json()
    zid = storage.create_zone(data.get("name", ""))
    return {"ok": True, "id": zid}


@app.post("/api/zones/{zone_id}/rename")
async def rename_zone(zone_id: str, request: Request):
    data = await request.json()
    storage.rename_zone(zone_id, data.get("name", ""))
    return {"ok": True}


@app.delete("/api/zones/{zone_id}")
async def delete_zone(zone_id: str):
    storage.delete_zone(zone_id)
    return {"ok": True}


@app.post("/api/groups")
async def create_group(request: Request):
    data = await request.json()
    gid = storage.create_group(data.get("name", ""), data.get("zone_id") or None)
    return {"ok": True, "id": gid}


@app.post("/api/groups/{group_id}/rename")
async def rename_group(group_id: str, request: Request):
    data = await request.json()
    storage.rename_group(group_id, data.get("name", ""))
    return {"ok": True}


@app.post("/api/groups/{group_id}/zone")
async def move_group(group_id: str, request: Request):
    data = await request.json()
    storage.move_group_to_zone(group_id, data.get("zone_id") or None)
    return {"ok": True}


@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: str):
    storage.delete_group(group_id)
    return {"ok": True}


@app.post("/api/groups/{group_id}/move")
async def move_group(group_id: str, request: Request):
    data = await request.json()
    storage.move_group(group_id, data.get("direction", "left"))
    return {"ok": True}


@app.get("/api/state")
async def state():
    agents, problems = storage.get_state(
        config_mod.CONFIG["agent_offline_after_seconds"]
    )
    zones, ungrouped = storage.get_structure()
    system = {
        "version": VERSION,
        "hostname": socket.gethostname(),
        "host": config_mod.CONFIG["host"],
        "port": config_mod.CONFIG["port"],
        "uptime_seconds": int(time.time() - START_TIME),
        "server_time": time.time(),
        "events_count": storage.get_events_count(),
    }
    return {
        "agents": agents,
        "problems": problems,
        "zones": zones,
        "ungrouped_groups": ungrouped,
        "system": system,
    }


@app.get("/api/events")
async def events():
    return {"events": storage.get_events(100)}


@app.post("/api/test-alert")
async def test_alert():
    alerts.send_test()
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config_mod.CONFIG["host"], port=config_mod.CONFIG["port"])

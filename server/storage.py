import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.db")
_lock = threading.Lock()
_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _gen_short_id(conn):
    while True:
        sid = "".join(secrets.choice(_ID_ALPHABET) for _ in range(4))
        if conn.execute("SELECT 1 FROM agents WHERE short_id=?", (sid,)).fetchone() is None:
            return sid


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        with _lock:
            yield conn
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents(
                agent_id TEXT PRIMARY KEY,
                hostname TEXT,
                first_seen REAL,
                last_seen REAL,
                status TEXT DEFAULT 'online'
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS devices(
                device_id TEXT,
                agent_id TEXT,
                name TEXT,
                type TEXT,
                status TEXT,
                message TEXT,
                last_checked REAL,
                prev_status TEXT,
                PRIMARY KEY(agent_id, device_id)
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                agent_id TEXT,
                device_id TEXT,
                kind TEXT,
                text TEXT
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zones(
                id TEXT PRIMARY KEY,
                name TEXT
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS groups(
                id TEXT PRIMARY KEY,
                zone_id TEXT,
                name TEXT
            )""")
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]
        if "state" not in cols:
            conn.execute("ALTER TABLE agents ADD COLUMN state TEXT DEFAULT 'active'")
        if "display_name" not in cols:
            conn.execute("ALTER TABLE agents ADD COLUMN display_name TEXT")
        dcols = [r["name"] for r in conn.execute("PRAGMA table_info(devices)").fetchall()]
        if "display_name" not in dcols:
            conn.execute("ALTER TABLE devices ADD COLUMN display_name TEXT")
        acols = [r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]
        if "group_id" not in acols:
            conn.execute("ALTER TABLE agents ADD COLUMN group_id TEXT")
        if "short_id" not in acols:
            conn.execute("ALTER TABLE agents ADD COLUMN short_id TEXT")
        if "local_ip" not in acols:
            conn.execute("ALTER TABLE agents ADD COLUMN local_ip TEXT")
        if "remote_ip" not in acols:
            conn.execute("ALTER TABLE agents ADD COLUMN remote_ip TEXT")
        rows = conn.execute("SELECT agent_id FROM agents WHERE short_id IS NULL").fetchall()
        for r in rows:
            conn.execute(
                "UPDATE agents SET short_id=? WHERE agent_id=?",
                (_gen_short_id(conn), r["agent_id"]),
            )
        gcols = [r["name"] for r in conn.execute("PRAGMA table_info(groups)").fetchall()]
        if "pos" not in gcols:
            conn.execute("ALTER TABLE groups ADD COLUMN pos INTEGER")
            rows = conn.execute("SELECT id FROM groups ORDER BY rowid").fetchall()
            for i, r in enumerate(rows, 1):
                conn.execute("UPDATE groups SET pos=? WHERE id=?", (i, r["id"]))


def add_event(evt):
    with _db() as conn:
        conn.execute(
            "INSERT INTO events(ts, agent_id, device_id, kind, text) VALUES(?,?,?,?,?)",
            (time.time(), evt.get("agent_id"), evt.get("device_id"),
             evt.get("kind"), evt.get("text")),
        )


def _group_prefix(conn, group_id):
    parts = []
    if group_id:
        g = conn.execute(
            "SELECT name, zone_id FROM groups WHERE id=?", (group_id,)
        ).fetchone()
        if g:
            if g["zone_id"]:
                z = conn.execute(
                    "SELECT name FROM zones WHERE id=?", (g["zone_id"],)
                ).fetchone()
                if z and z["name"]:
                    parts.append(z["name"])
            if g["name"]:
                parts.append(g["name"])
    return parts


def _join(parts):
    return " · ".join(p for p in parts if p)


def _agent_label(conn, agent_id, hostname):
    row = conn.execute(
        "SELECT display_name, short_id FROM agents WHERE agent_id=?", (agent_id,)
    ).fetchone()
    if row:
        if row["display_name"]:
            return row["display_name"]
        if row["short_id"]:
            return row["short_id"]
    return hostname


def _agent_path(conn, agent_id, hostname):
    row = conn.execute(
        "SELECT group_id FROM agents WHERE agent_id=?", (agent_id,)
    ).fetchone()
    group_id = row["group_id"] if row else None
    label = _agent_label(conn, agent_id, hostname)
    return _join(_group_prefix(conn, group_id) + [label])


def _device_path(conn, agent_id, device_id, name):
    arow = conn.execute(
        "SELECT group_id FROM agents WHERE agent_id=?", (agent_id,)
    ).fetchone()
    group_id = arow["group_id"] if arow else None
    agent_label = _agent_label(conn, agent_id, "")
    drow = conn.execute(
        "SELECT display_name FROM devices WHERE agent_id=? AND device_id=?",
        (agent_id, device_id),
    ).fetchone()
    dlabel = (drow["display_name"] or name) if drow else name
    return _join(_group_prefix(conn, group_id) + [agent_label, dlabel])


def _upsert_devices(conn, agent_id, devices, now, transitions):
    for d in devices:
        did = d.get("id")
        if not did:
            continue
        new_status = d.get("status")
        name = d.get("name", "")
        dtype = d.get("type", "")
        msg = d.get("message", "")
        existing = conn.execute(
            "SELECT status FROM devices WHERE agent_id=? AND device_id=?",
            (agent_id, did),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO devices(device_id, agent_id, name, type, status, message, "
                "last_checked, prev_status) VALUES(?,?,?,?,?,?,?,?)",
                (did, agent_id, name, dtype, new_status, msg, now, new_status),
            )
            if new_status == "down":
                path = _device_path(conn, agent_id, did, name)
                transitions.append({
                    "agent_id": agent_id, "device_id": did, "kind": "device_down",
                    "text": "Устройство %s: ПРОБЛЕМА (%s)" % (path, msg or "—"),
                })
        else:
            prev = existing["status"]
            conn.execute(
                "UPDATE devices SET name=?, type=?, status=?, message=?, last_checked=?, "
                "prev_status=? WHERE agent_id=? AND device_id=?",
                (name, dtype, new_status, msg, now, prev, agent_id, did),
            )
            if prev != new_status:
                path = _device_path(conn, agent_id, did, name)
                if new_status == "down":
                    transitions.append({
                        "agent_id": agent_id, "device_id": did, "kind": "device_down",
                        "text": "Устройство %s: ПРОБЛЕМА (%s)" % (path, msg or "—"),
                    })
                else:
                    transitions.append({
                        "agent_id": agent_id, "device_id": did, "kind": "device_recovered",
                        "text": "Устройство %s: восстановлено" % path,
                    })


def process_heartbeat(agent_id, hostname, ts, devices, auto_approve=True, local_ip="", remote_ip=""):
    now = time.time()
    transitions = []
    code = "ok"
    with _db() as conn:
        row = conn.execute(
            "SELECT status, state FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if row is None:
            state = "active" if auto_approve else "pending"
            conn.execute(
                "INSERT INTO agents(agent_id, hostname, first_seen, last_seen, status, state, "
                "short_id, local_ip, remote_ip) VALUES(?,?,?,?,?,?,?,?,?)",
                (agent_id, hostname, now, now, "online", state, _gen_short_id(conn),
                 local_ip or None, remote_ip or None),
            )
            _upsert_devices(conn, agent_id, devices, now, transitions)
            code = "pending" if state == "pending" else "ok"
        else:
            state = row["state"] or "active"
            if state == "disabled":
                return "disabled", []
            conn.execute(
                "UPDATE agents SET hostname=?, last_seen=?, status='online', local_ip=?, remote_ip=? "
                "WHERE agent_id=?",
                (hostname, now, local_ip or None, remote_ip or None, agent_id),
            )
            if row["status"] == "offline":
                transitions.append({
                    "agent_id": agent_id, "device_id": None, "kind": "agent_online",
                    "text": "Агент %s снова на связи" % _agent_path(conn, agent_id, hostname),
                })
            _upsert_devices(conn, agent_id, devices, now, transitions)
            code = "pending" if state == "pending" else "ok"

        # синхронизация: удаляем устройства, которых больше нет в heartbeat
        reported = [d.get("id") for d in devices if d.get("id")]
        if reported:
            q = ",".join("?" * len(reported))
            conn.execute(
                "DELETE FROM devices WHERE agent_id=? AND device_id NOT IN (%s)" % q,
                [agent_id] + reported,
            )
        else:
            conn.execute("DELETE FROM devices WHERE agent_id=?", (agent_id,))

    for t in transitions:
        add_event(t)
    return code, transitions


def check_offline(offline_after):
    now = time.time()
    transitions = []
    with _db() as conn:
        rows = conn.execute(
            "SELECT agent_id, hostname, last_seen FROM agents "
            "WHERE status='online' AND state='active'"
        ).fetchall()
        for r in rows:
            if now - r["last_seen"] > offline_after:
                conn.execute(
                    "UPDATE agents SET status='offline' WHERE agent_id=?", (r["agent_id"],)
                )
                transitions.append({
                    "agent_id": r["agent_id"], "device_id": None, "kind": "agent_offline",
                    "text": "Агент %s офлайн (нет heartbeat)" % _agent_path(conn, r["agent_id"], r["hostname"]),
                })
    for t in transitions:
        add_event(t)
    return transitions


def set_agent_state(agent_id, state):
    with _db() as conn:
        conn.execute(
            "UPDATE agents SET state=? WHERE agent_id=?", (state, agent_id)
        )


def get_agent_short_id(agent_id):
    with _db() as conn:
        row = conn.execute(
            "SELECT short_id FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
    return row["short_id"] if row else None


def rename_agent(agent_id, name):
    name = (name or "").strip() or None
    with _db() as conn:
        conn.execute(
            "UPDATE agents SET display_name=? WHERE agent_id=?", (name, agent_id)
        )


def rename_device(agent_id, device_id, name):
    name = (name or "").strip() or None
    with _db() as conn:
        conn.execute(
            "UPDATE devices SET display_name=? WHERE agent_id=? AND device_id=?",
            (name, agent_id, device_id),
        )


def delete_agent(agent_id):
    with _db() as conn:
        conn.execute("DELETE FROM devices WHERE agent_id=?", (agent_id,))
        conn.execute("DELETE FROM events WHERE agent_id=?", (agent_id,))
        conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))


def create_zone(name):
    zid = str(uuid.uuid4())
    with _db() as conn:
        conn.execute("INSERT INTO zones(id, name) VALUES(?,?)", (zid, name.strip()))
    return zid


def rename_zone(zone_id, name):
    with _db() as conn:
        conn.execute("UPDATE zones SET name=? WHERE id=?", (name.strip(), zone_id))


def delete_zone(zone_id):
    with _db() as conn:
        conn.execute("UPDATE groups SET zone_id=NULL WHERE zone_id=?", (zone_id,))
        conn.execute("DELETE FROM zones WHERE id=?", (zone_id,))


def create_group(name, zone_id=None):
    gid = str(uuid.uuid4())
    with _db() as conn:
        row = conn.execute("SELECT MAX(pos) AS m FROM groups").fetchone()
        pos = (row["m"] or 0) + 1
        conn.execute(
            "INSERT INTO groups(id, zone_id, name, pos) VALUES(?,?,?,?)",
            (gid, zone_id or None, name.strip(), pos),
        )
    return gid


def move_group(group_id, direction):
    with _db() as conn:
        g = conn.execute(
            "SELECT zone_id, pos FROM groups WHERE id=?", (group_id,)
        ).fetchone()
        if g is None:
            return
        zone = g["zone_id"]
        if zone:
            sibs = conn.execute(
                "SELECT id, pos FROM groups WHERE zone_id=? ORDER BY pos", (zone,)
            ).fetchall()
        else:
            sibs = conn.execute(
                "SELECT id, pos FROM groups WHERE zone_id IS NULL ORDER BY pos"
            ).fetchall()
        ids = [s["id"] for s in sibs]
        if group_id not in ids:
            return
        idx = ids.index(group_id)
        target = idx - 1 if direction == "left" else idx + 1
        if target < 0 or target >= len(ids):
            return
        a, b = sibs[idx], sibs[target]
        conn.execute("UPDATE groups SET pos=? WHERE id=?", (b["pos"], a["id"]))
        conn.execute("UPDATE groups SET pos=? WHERE id=?", (a["pos"], b["id"]))


def rename_group(group_id, name):
    with _db() as conn:
        conn.execute("UPDATE groups SET name=? WHERE id=?", (name.strip(), group_id))


def delete_group(group_id):
    with _db() as conn:
        conn.execute("UPDATE agents SET group_id=NULL WHERE group_id=?", (group_id,))
        conn.execute("DELETE FROM groups WHERE id=?", (group_id,))


def assign_agent_group(agent_id, group_id):
    group_id = group_id or None
    with _db() as conn:
        conn.execute(
            "UPDATE agents SET group_id=? WHERE agent_id=?", (group_id, agent_id)
        )


def move_group_to_zone(group_id, zone_id):
    zone_id = zone_id or None
    with _db() as conn:
        conn.execute("UPDATE groups SET zone_id=? WHERE id=?", (zone_id, group_id))


def get_structure():
    with _db() as conn:
        zones = conn.execute("SELECT * FROM zones ORDER BY rowid").fetchall()
        groups = conn.execute("SELECT * FROM groups ORDER BY pos, name").fetchall()
    zones_out = []
    for z in zones:
        zones_out.append({
            "id": z["id"], "name": z["name"],
            "groups": [{"id": g["id"], "name": g["name"]}
                       for g in groups if g["zone_id"] == z["id"]],
        })
    ungrouped = [{"id": g["id"], "name": g["name"]} for g in groups if not g["zone_id"]]
    return zones_out, ungrouped


def get_state(offline_after):
    now = time.time()
    with _db() as conn:
        agents = conn.execute("SELECT * FROM agents ORDER BY hostname").fetchall()
        result = []
        for a in agents:
            state = a["state"] or "active"
            if state == "active":
                online = a["status"] == "online" and (now - a["last_seen"]) <= offline_after
                status = "online" if online else "offline"
            else:
                status = state
            devices = conn.execute(
                "SELECT * FROM devices WHERE agent_id=? ORDER BY name", (a["agent_id"],)
            ).fetchall()
            alabel = a["display_name"] or a["short_id"] or a["hostname"]
            agent_path = _join(_group_prefix(conn, a["group_id"]) + [alabel])
            dev_list = []
            for d in devices:
                dlabel = d["display_name"] or d["name"]
                eff_status = d["status"]
                eff_message = d["message"]
                if status != "online":
                    eff_status = "down"
                    eff_message = {
                        "offline": "агент офлайн",
                        "disabled": "агент отключён",
                        "pending": "ожидает подтверждения",
                    }.get(status, "нет данных")
                dev_list.append({
                    "id": d["device_id"],
                    "name": d["name"],
                    "display_name": d["display_name"],
                    "label": dlabel,
                    "path": _join(_group_prefix(conn, a["group_id"]) + [alabel, dlabel]),
                    "type": d["type"],
                    "status": d["status"],
                    "message": d["message"],
                    "eff_status": eff_status,
                    "eff_message": eff_message,
                    "last_checked": d["last_checked"],
                })
            result.append({
                "agent_id": a["agent_id"],
                "hostname": a["hostname"],
                "display_name": a["display_name"],
                "label": alabel,
                "short_id": a["short_id"],
                "local_ip": a["local_ip"],
                "remote_ip": a["remote_ip"],
                "path": agent_path,
                "group_id": a["group_id"],
                "state": state,
                "status": status,
                "last_seen": a["last_seen"],
                "devices": dev_list,
            })

    problems = []
    for a in result:
        if a["state"] != "active":
            continue
        if a["status"] == "offline":
            problems.append({
                "agent": a["path"],
                "device": None,
                "kind": "agent",
                "text": "Агент офлайн (нет heartbeat)",
            })
        for d in a["devices"]:
            if d["status"] == "down":
                problems.append({
                    "agent": a["path"],
                    "device": d["path"],
                    "kind": "device",
                    "text": d["message"] or "Проблема",
                })
    return result, problems


def get_events(limit=100):
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_events_count():
    with _db() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()
    return row["c"]

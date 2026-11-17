import json
import os
import platform
import socket
import sys
import uuid


def app_data_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "5agent")
    else:
        d = os.path.join(os.path.expanduser("~"), ".config", "5agent")
    os.makedirs(d, exist_ok=True)
    return d


def config_path():
    return os.path.join(app_data_dir(), "config.json")


def log_path():
    return os.path.join(app_data_dir(), "agent.log")


DEFAULTS = {
    "agent_id": None,
    "server_url": "http://127.0.0.1:8080",
    "poll_seconds": 10,
    "devices": [],
}


def load_config(path=None):
    path = path or config_path()
    data = dict(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:
            pass
    if not data.get("agent_id"):
        data["agent_id"] = str(uuid.uuid4())
    if not isinstance(data.get("devices"), list):
        data["devices"] = []
    return data


def save_config(config, path=None):
    path = path or config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def hostname():
    return platform.node() or "unknown"


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip:
            return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return ""

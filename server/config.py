import json
import os

DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8080,
    "agent_offline_after_seconds": 35,
    "auto_approve_agents": False,
    "alerts": {
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "use_tls": True,
            "username": "",
            "password": "",
            "from": "",
            "to": [],
        },
        "notify_on_recovery": True,
    },
}


def _deep_update(base, update):
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


def load_config(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    data = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _deep_update(data, loaded)
        except Exception:
            pass
    return data


CONFIG = load_config()
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
_CONFIG_MTIME = os.path.getmtime(_CONFIG_PATH) if os.path.exists(_CONFIG_PATH) else None


def reload_config():
    global CONFIG
    CONFIG = load_config()


def reload_if_changed():
    global _CONFIG_MTIME
    if not os.path.exists(_CONFIG_PATH):
        return
    mtime = os.path.getmtime(_CONFIG_PATH)
    if mtime != _CONFIG_MTIME:
        _CONFIG_MTIME = mtime
        reload_config()

import json
import urllib.error
import urllib.request


def _safe_json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def send_heartbeat(server_url, payload, timeout=6):
    url = (server_url or "").rstrip("/") + "/api/heartbeat"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _safe_json(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, _safe_json(e.read())

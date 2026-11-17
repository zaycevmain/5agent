import os
import threading
import time

import checkers
import config as config_mod
import gui
import sender
import tray


class App:
    def __init__(self):
        self.config = config_mod.load_config()
        self.running = False
        self.deauthorized = False
        self.tray_active = False
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.tray_icon = None
        self.window = gui.ConfigWindow(
            self.config,
            on_start=self.start,
            on_stop=self.stop,
            on_save=self.save,
            on_exit=self.exit_app,
            on_close=self.close,
            on_kill=self.kill,
        )

    def save(self):
        config_mod.save_config(self.config)

    def kill(self):
        try:
            self.save()
        except Exception:
            pass
        os._exit(0)

    def start(self):
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.window.ui_queue.put({"action": "running", "running": True})
        self._start_tray()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.stop_event.set()
        self.window.ui_queue.put({"action": "running", "running": False})
        self.window.ui_queue.put({"action": "show"})

    def _monitor_loop(self):
        while not self.stop_event.is_set():
            results = []
            for dev in self.config.get("devices", []):
                ok, msg = checkers.check_device(dev)
                results.append({
                    "id": dev["id"],
                    "name": dev.get("name", ""),
                    "type": dev.get("type", ""),
                    "status": "ok" if ok else "down",
                    "message": msg,
                })
            self.window.ui_queue.put({"action": "results", "results": results})

            payload = {
                "agent_id": self.config.get("agent_id"),
                "hostname": config_mod.hostname(),
                "ts": time.time(),
                "local_ip": config_mod.local_ip(),
                "devices": results,
            }
            server_url = self.config.get("server_url", "")
            try:
                status_code, body = sender.send_heartbeat(server_url, payload)
                sid = body.get("short_id")
                if sid and sid != self.config.get("short_id"):
                    self.config["short_id"] = sid
                    self.save()
                    self.window.ui_queue.put({"action": "short_id", "text": sid})
                if status_code == 200:
                    self.deauthorized = False
                    if body.get("state") == "pending":
                        self.window.ui_queue.put({"action": "conn", "state": "pending"})
                        self.window.ui_queue.put({"action": "status", "ok": False,
                                                  "text": "Ожидает подтверждения на сервере"})
                    else:
                        self.window.ui_queue.put({"action": "conn", "state": "connected"})
                        self.window.ui_queue.put({"action": "status", "ok": True,
                                                  "text": "Отправлено: %s" % time.strftime("%H:%M:%S")})
                elif status_code == 403 and body.get("reason") == "disabled":
                    self.deauthorized = True
                    self.window.ui_queue.put({"action": "conn", "state": "deauthorized"})
                    self.window.ui_queue.put({"action": "status", "ok": False,
                                              "text": "Деавторизован — сервер отключил агента"})
                else:
                    self.window.ui_queue.put({"action": "conn", "state": "disconnected"})
                    self.window.ui_queue.put({"action": "status", "ok": False,
                                              "text": "Ошибка сервера: HTTP %s" % status_code})
            except Exception as e:
                self.window.ui_queue.put({"action": "conn", "state": "disconnected"})
                self.window.ui_queue.put({"action": "status", "ok": False,
                                          "text": "Ошибка сервера: %s" % e})

            wait = max(self.config.get("poll_seconds", 10), 60) if self.deauthorized else self.config.get("poll_seconds", 10)
            self.stop_event.wait(wait)

    def _start_tray(self):
        if self.tray_icon is None:
            self.tray_icon = tray.run_tray(self.request_open, self.stop, self.request_exit)
        if self.tray_icon is not None:
            self.tray_icon.run_detached()
            self.tray_active = True
            return True
        return False

    def request_open(self):
        self.window.ui_queue.put({"action": "show"})

    def request_exit(self):
        self.window.ui_queue.put({"action": "exit"})

    def close(self):
        if self.tray_active:
            self.window.hide()
        else:
            self.exit_app()

    def exit_app(self):
        self.stop()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.save()
        try:
            self.window.root.destroy()
        except Exception:
            pass

    def run(self):
        self.start()
        self.window.run()


def main():
    App().run()


if __name__ == "__main__":
    main()

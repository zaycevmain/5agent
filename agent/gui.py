import queue
import tkinter as tk
from tkinter import ttk

import checkers

TYPE_LABELS = {
    "process": "Процесс",
    "window": "Окно",
    "com": "COM-порт",
    "printer": "Принтер",
    "rfid": "RFID",
    "custom": "Другое",
}

CUSTOM_TYPES = {
    "tcp": "TCP-порт (host:port)",
    "ping": "Ping (host)",
    "usb": "USB-HID (VID/PID или имя)",
    "com": "COM-порт",
    "process": "Процесс",
    "printer": "Принтер",
}

CONN = {
    "idle": ("#8b96ad", "Не запущен"),
    "connected": ("#22c55e", "Подключено"),
    "pending": ("#f59e0b", "Ожидает подтверждения"),
    "deauthorized": ("#ef4444", "Отключён сервером"),
    "disconnected": ("#ef4444", "Нет связи с сервером"),
}


def describe_device(device):
    t = (device.get("type") or "").lower()
    spec = device.get("spec") or {}
    if t == "process":
        return spec.get("process_name", "")
    if t == "window":
        out = spec.get("process", "")
        if spec.get("cmdline"):
            c = spec["cmdline"]
            if len(c) > 60:
                c = c[:60] + "..."
            out = (out + " · " + c) if out else c
        return out
    if t == "com":
        return spec.get("port", "")
    if t == "printer":
        return spec.get("printer_name", "")
    if t == "rfid":
        mode = (spec.get("mode") or "usb").lower()
        if mode == "com":
            return "COM %s" % spec.get("port", "")
        if mode == "tcp":
            return "%s:%s" % (spec.get("host", ""), spec.get("port", ""))
        return "VID %s PID %s" % (spec.get("vid", "-"), spec.get("pid", "-"))
    if t == "custom":
        ct = (spec.get("check_type") or "").lower()
        if ct in ("tcp", "ping"):
            return "%s %s:%s" % (ct, spec.get("host", ""), spec.get("port", ""))
        if ct == "usb":
            return spec.get("hwid") or spec.get("name") or ("usb VID %s PID %s" % (spec.get("vid", "-"), spec.get("pid", "-")))
        if ct == "com":
            return "com %s" % spec.get("port", "")
        if ct == "process":
            return "process %s" % spec.get("process_name", "")
        if ct == "printer":
            return "printer %s" % spec.get("printer_name", "")
        return ""
    return ""


def _ask_list_or_manual(root, title, label, items):
    dlg = tk.Toplevel(root)
    dlg.title(title)
    dlg.transient(root)
    dlg.grab_set()
    dlg.resizable(False, False)
    result = {"value": None}

    frame = ttk.Frame(dlg, padding=10)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text=label).pack(anchor="w")
    listbox = tk.Listbox(frame, height=10)
    listbox.pack(fill="both", expand=True, pady=4)
    for it in items:
        listbox.insert("end", it)

    ttk.Label(frame, text="Или вручную:").pack(anchor="w", pady=(8, 0))
    entry = ttk.Entry(frame)
    entry.pack(fill="x", pady=4)

    btns = ttk.Frame(frame)
    btns.pack(fill="x", pady=(8, 0))

    def ok():
        sel = listbox.curselection()
        if sel:
            result["value"] = listbox.get(sel[0])
        else:
            result["value"] = entry.get().strip() or None
        dlg.destroy()

    def cancel():
        result["value"] = None
        dlg.destroy()

    ttk.Button(btns, text="OK", command=ok).pack(side="right")
    ttk.Button(btns, text="Отмена", command=cancel).pack(side="right", padx=4)
    dlg.protocol("WM_DELETE_WINDOW", cancel)
    entry.bind("<Return>", lambda e: ok())
    listbox.bind("<Double-Button-1>", lambda e: ok())
    dlg.wait_window()
    return result.get("value")


def _ask_rfid(root):
    dlg = tk.Toplevel(root)
    dlg.title("RFID-считыватель")
    dlg.transient(root)
    dlg.grab_set()
    dlg.resizable(False, False)
    result = {"spec": None, "name": None}

    frame = ttk.Frame(dlg, padding=10)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Название:").grid(row=0, column=0, sticky="w")
    name_entry = ttk.Entry(frame, width=32)
    name_entry.grid(row=0, column=1, sticky="we", pady=2)

    mode = tk.StringVar(value="usb")
    ttk.Label(frame, text="Тип подключения:").grid(row=1, column=0, sticky="w")
    mode_box = ttk.Combobox(frame, textvariable=mode, state="readonly",
                            values=["usb", "com", "tcp"], width=28)
    mode_box.grid(row=1, column=1, sticky="we", pady=2)

    usb_frame = ttk.LabelFrame(frame, text="USB (Hardware ID)")
    usb_frame.grid(row=2, column=0, columnspan=2, sticky="we", pady=4)
    ttk.Label(usb_frame, text="Hardware ID:").grid(row=0, column=0, sticky="w")
    hwid_entry = ttk.Entry(usb_frame, width=32)
    hwid_entry.grid(row=0, column=1, sticky="we", pady=2)
    ttk.Label(usb_frame, text="например USB\\VID_203A&PID_FFFB\\...",
              foreground="#888").grid(row=1, column=0, columnspan=2, sticky="w")
    ttk.Label(usb_frame, text="или VID:").grid(row=2, column=0, sticky="w", pady=(4, 0))
    vid_entry = ttk.Entry(usb_frame, width=12)
    vid_entry.grid(row=2, column=1, sticky="w", pady=(4, 0), padx=2)
    ttk.Label(usb_frame, text="PID:").grid(row=2, column=2, sticky="w", pady=(4, 0))
    pid_entry = ttk.Entry(usb_frame, width=12)
    pid_entry.grid(row=2, column=3, sticky="w", pady=(4, 0), padx=2)
    ttk.Label(usb_frame, text="или имя (подстрока):").grid(row=3, column=0, sticky="w", pady=2)
    name_hid_entry = ttk.Entry(usb_frame, width=32)
    name_hid_entry.grid(row=3, column=1, columnspan=3, sticky="we", pady=2)

    com_frame = ttk.LabelFrame(frame, text="COM-порт")
    com_frame.grid(row=3, column=0, columnspan=2, sticky="we", pady=4)
    ttk.Label(com_frame, text="Порт:").grid(row=0, column=0, sticky="w")
    port_entry = ttk.Entry(com_frame, width=32)
    port_entry.grid(row=0, column=1, sticky="we", pady=2)

    tcp_frame = ttk.LabelFrame(frame, text="TCP")
    tcp_frame.grid(row=4, column=0, columnspan=2, sticky="we", pady=4)
    ttk.Label(tcp_frame, text="Host:").grid(row=0, column=0, sticky="w")
    host_entry = ttk.Entry(tcp_frame, width=20)
    host_entry.grid(row=0, column=1, sticky="we", pady=2)
    ttk.Label(tcp_frame, text="Port:").grid(row=0, column=2, sticky="w")
    tport_entry = ttk.Entry(tcp_frame, width=8)
    tport_entry.grid(row=0, column=3, sticky="we", pady=2)

    def collect():
        m = mode.get()
        spec = {"mode": m}
        if m == "usb":
            spec["hwid"] = hwid_entry.get().strip()
            spec["vid"] = vid_entry.get().strip()
            spec["pid"] = pid_entry.get().strip()
            spec["name"] = name_hid_entry.get().strip()
        elif m == "com":
            spec["port"] = port_entry.get().strip()
        else:
            spec["host"] = host_entry.get().strip()
            spec["port"] = tport_entry.get().strip()
        result["spec"] = spec
        result["name"] = name_entry.get().strip() or ("RFID %s" % m)
        dlg.destroy()

    def cancel():
        dlg.destroy()

    btns = ttk.Frame(frame)
    btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Button(btns, text="OK", command=collect).pack(side="right")
    ttk.Button(btns, text="Отмена", command=cancel).pack(side="right", padx=4)
    dlg.protocol("WM_DELETE_WINDOW", cancel)

    def sync_frames(*_):
        m = mode.get()
        for w in (usb_frame, com_frame, tcp_frame):
            w.grid_remove()
        {"usb": usb_frame, "com": com_frame, "tcp": tcp_frame}[m].grid()

    mode.trace_add("write", sync_frames)
    sync_frames()
    dlg.wait_window()
    return result


def _ask_custom(root):
    dlg = tk.Toplevel(root)
    dlg.title("Другое оборудование")
    dlg.transient(root)
    dlg.grab_set()
    dlg.resizable(False, False)
    result = {"spec": None, "name": None}

    frame = ttk.Frame(dlg, padding=10)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Название:").grid(row=0, column=0, sticky="w")
    name_entry = ttk.Entry(frame, width=32)
    name_entry.grid(row=0, column=1, sticky="we", pady=2)

    ctype = tk.StringVar(value="tcp")
    ttk.Label(frame, text="Тип проверки:").grid(row=1, column=0, sticky="w")
    type_box = ttk.Combobox(frame, textvariable=ctype, state="readonly",
                            values=list(CUSTOM_TYPES.keys()), width=28)
    type_box.grid(row=1, column=1, sticky="we", pady=2)

    host_label = ttk.Label(frame, text="Host:")
    host_label.grid(row=2, column=0, sticky="w")
    host_entry = ttk.Entry(frame, width=32)
    host_entry.grid(row=2, column=1, sticky="we", pady=2)

    port_label = ttk.Label(frame, text="Port:")
    port_label.grid(row=3, column=0, sticky="w")
    port_entry = ttk.Entry(frame, width=32)
    port_entry.grid(row=3, column=1, sticky="we", pady=2)

    vid_label = ttk.Label(frame, text="VID:")
    vid_label.grid(row=4, column=0, sticky="w")
    vid_entry = ttk.Entry(frame, width=32)
    vid_entry.grid(row=4, column=1, sticky="we", pady=2)

    pid_label = ttk.Label(frame, text="PID:")
    pid_label.grid(row=5, column=0, sticky="w")
    pid_entry = ttk.Entry(frame, width=32)
    pid_entry.grid(row=5, column=1, sticky="we", pady=2)

    extra_label = ttk.Label(frame, text="Значение (имя/порт):")
    extra_label.grid(row=6, column=0, sticky="w")
    extra_entry = ttk.Entry(frame, width=32)
    extra_entry.grid(row=6, column=1, sticky="we", pady=2)

    hints = {
        "tcp": ("Host:", "Port:", "", "", ""),
        "ping": ("Host:", "", "", "", ""),
        "usb": ("Hardware ID (USB\\VID_203A&PID_FFFB\\...):", "", "", "", ""),
        "com": ("Порт:", "", "", "", ""),
        "process": ("Имя процесса:", "", "", "", ""),
        "printer": ("Имя принтера:", "", "", "", ""),
    }

    labels = [host_label, port_label, vid_label, pid_label, extra_label]
    entries = [host_entry, port_entry, vid_entry, pid_entry, extra_entry]

    def sync_fields(*_):
        h = hints.get(ctype.get(), ("", "", "", "", ""))
        for i, lab in enumerate(labels):
            text = h[i] if i < len(h) else ""
            lab.config(text=text or " ")
            if text:
                lab.grid()
                entries[i].grid()
            else:
                lab.grid_remove()
                entries[i].grid_remove()

    ctype.trace_add("write", sync_fields)
    sync_fields()

    def collect():
        t = ctype.get()
        spec = {"check_type": t}
        vals = [e.get().strip() for e in entries]
        if t == "tcp":
            spec["host"] = vals[0]
            spec["port"] = vals[1]
        elif t == "ping":
            spec["host"] = vals[0]
        elif t == "usb":
            spec["hwid"] = vals[0]
            spec["name"] = vals[0]
        elif t == "com":
            spec["port"] = vals[0]
        elif t == "process":
            spec["process_name"] = vals[0]
        elif t == "printer":
            spec["printer_name"] = vals[0]
        result["spec"] = spec
        result["name"] = name_entry.get().strip() or ("%s %s" % (t, vals[0]))
        dlg.destroy()

    def cancel():
        dlg.destroy()

    btns = ttk.Frame(frame)
    btns.grid(row=7, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Button(btns, text="OK", command=collect).pack(side="right")
    ttk.Button(btns, text="Отмена", command=cancel).pack(side="right", padx=4)
    dlg.protocol("WM_DELETE_WINDOW", cancel)
    dlg.wait_window()
    return result


def _ask_window(root):
    dlg = tk.Toplevel(root)
    dlg.title("Окно")
    dlg.transient(root)
    dlg.grab_set()
    dlg.geometry("620x460")
    result = {"items": []}
    windows = {"items": checkers.list_windows()}

    frame = ttk.Frame(dlg, padding=10)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Выберите открытые окна (Ctrl/Shift — несколько):").pack(anchor="w")
    listbox = tk.Listbox(frame, height=14, selectmode="extended")
    listbox.pack(fill="both", expand=True, pady=4)

    def fill():
        windows["items"] = checkers.list_windows()
        listbox.delete(0, "end")
        for w in windows["items"]:
            label = w["title"]
            if w.get("process"):
                label += "  —  " + w["process"]
            listbox.insert("end", label)

    fill()
    ttk.Button(frame, text="Обновить список", command=fill).pack(anchor="w", pady=2)

    ttk.Label(frame, text="Или заголовок (подстроку) вручную:").pack(anchor="w", pady=(8, 0))
    entry = ttk.Entry(frame)
    entry.pack(fill="x", pady=4)

    ttk.Label(frame, text="Агент сам запомнит процесс и командную строку окна — "
                          "отслеживание не сломается, если заголовок поменяется.",
              foreground="#888", wraplength=560, justify="left").pack(anchor="w", pady=(0, 6))

    def add():
        for i in listbox.curselection():
            w = windows["items"][i]
            result["items"].append({
                "name": w["title"],
                "spec": {
                    "title": w["title"],
                    "process": w.get("process", ""),
                    "cmdline": w.get("cmdline", ""),
                },
            })
        manual = entry.get().strip()
        if manual:
            result["items"].append({
                "name": manual,
                "spec": {"title": manual, "process": "", "cmdline": ""},
            })
        dlg.destroy()

    def cancel():
        dlg.destroy()

    btns = ttk.Frame(frame)
    btns.pack(fill="x", pady=(8, 0))
    ttk.Button(btns, text="Добавить", command=add).pack(side="right")
    ttk.Button(btns, text="Отмена", command=cancel).pack(side="right", padx=4)
    dlg.protocol("WM_DELETE_WINDOW", cancel)
    listbox.bind("<Double-Button-1>", lambda e: add())
    dlg.wait_window()
    return result


class ConfigWindow:
    def __init__(self, config_data, on_start, on_stop, on_save, on_exit, on_close, on_kill):
        self.config_data = config_data
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_save = on_save
        self.on_exit = on_exit
        self.on_close = on_close
        self.on_kill = on_kill
        self.ui_queue = queue.Queue()
        self.running = False

        self.root = tk.Tk()
        self.root.title("5agent — мониторинг оборудования")
        self.root.geometry("800x560")
        self.root.minsize(680, 440)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_style()

        self.server_var = tk.StringVar(value=config_data.get("server_url", ""))
        self.poll_var = tk.StringVar(value=str(config_data.get("poll_seconds", 10)))
        self.status_var = tk.StringVar(value="")
        _sid = config_data.get("short_id", "")
        self.id_var = tk.StringVar(value=("ID: " + _sid) if _sid else "")

        self._build()
        self._refresh_tree()
        self.root.after(200, self._poll_queue)

    def _setup_style(self):
        bg = "#111827"
        bg2 = "#1a2333"
        fg = "#e7ecf7"
        muted = "#8b96ad"
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background=bg, foreground=fg, fieldbackground=bg2,
                        bordercolor="#2c3648", lightcolor=bg2, darkcolor=bg2,
                        troughcolor=bg2, insertcolor=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("Header.TLabel", background=bg, foreground=fg,
                        font=("Segoe UI", 14, "bold"))
        style.configure("Muted.TLabel", background=bg, foreground=muted)
        style.configure("TButton", background=bg2, foreground=fg, bordercolor="#2c3648",
                        focuscolor=bg2, padding=(10, 5))
        style.map("TButton", background=[("active", "#24314a")])
        style.configure("Accent.TButton", background="#16a34a", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#15803d")])
        style.configure("Danger.TButton", background="#3a1418", foreground="#f87171")
        style.map("Danger.TButton", background=[("active", "#4a1e22")])
        style.configure("TEntry", fieldbackground=bg2, foreground=fg)
        style.configure("Treeview", background=bg2, fieldbackground=bg2, foreground=fg,
                        bordercolor="#2c3648")
        style.configure("Treeview.Heading", background="#1a2333", foreground=fg,
                        bordercolor="#2c3648")
        style.map("Treeview", background=[("selected", "#24314a")],
                  foreground=[("selected", fg)])
        style.configure("TCombobox", fieldbackground=bg2, background=bg2, foreground=fg)
        style.configure("TLabelFrame", background=bg)
        style.configure("TLabelFrame.Label", background=bg, foreground=fg)
        self.root.configure(bg=bg)

    def _build(self):
        bg = "#111827"
        padx = 12

        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=padx, pady=(14, 8))
        ttk.Label(header, text="5agent", style="Header.TLabel").pack(side="left")
        self.conn_dot = tk.Label(header, text="●", font=("Segoe UI", 13), bg=bg, fg="#8b96ad")
        self.conn_dot.pack(side="left", padx=(12, 0))
        self.conn_label = ttk.Label(header, text="Не запущен", style="Muted.TLabel")
        self.conn_label.pack(side="left", padx=(4, 0))
        self.id_label = ttk.Label(header, textvariable=self.id_var, style="Muted.TLabel")
        self.id_label.pack(side="left", padx=(10, 0))
        self.run_btn = ttk.Button(header, text="Запустить", style="Accent.TButton",
                                  command=self._toggle_run)
        self.run_btn.pack(side="right")
        ttk.Button(header, text="Сохранить", command=self._save).pack(side="right", padx=6)

        cfg = ttk.Frame(self.root)
        cfg.pack(fill="x", padx=padx, pady=4)
        ttk.Label(cfg, text="Сервер:").pack(side="left")
        self.server_entry = ttk.Entry(cfg, textvariable=self.server_var, width=34)
        self.server_entry.pack(side="left", padx=6)
        ttk.Label(cfg, text="Интервал (сек):").pack(side="left", padx=(14, 0))
        self.poll_entry = ttk.Entry(cfg, textvariable=self.poll_var, width=6)
        self.poll_entry.pack(side="left", padx=6)

        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill="x", padx=padx, pady=(10, 4))
        ttk.Label(toolbar, text="Добавить:", style="Muted.TLabel").pack(side="left")
        for text, cmd in [
            ("Процесс", self._add_process),
            ("Окно", self._add_window),
            ("COM-порт", self._add_com),
            ("Принтер", self._add_printer),
            ("RFID", self._add_rfid),
            ("Другое", self._add_custom),
        ]:
            ttk.Button(toolbar, text=text, command=cmd).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Удалить", style="Danger.TButton",
                   command=self._remove_selected).pack(side="left", padx=(10, 0))

        tree_frame = ttk.Frame(self.root)
        tree_frame.pack(fill="both", expand=True, padx=padx, pady=6)

        self.tree = ttk.Treeview(tree_frame, columns=("name", "type", "detail", "status"),
                                 show="headings", height=12)
        self.tree.heading("name", text="Название")
        self.tree.heading("type", text="Тип")
        self.tree.heading("detail", text="Параметры")
        self.tree.heading("status", text="Статус")
        self.tree.column("name", width=200)
        self.tree.column("type", width=90)
        self.tree.column("detail", width=300)
        self.tree.column("status", width=120)
        self.tree.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        status_bar = ttk.Frame(self.root)
        status_bar.pack(fill="x", padx=padx, pady=(0, 12))
        self.status_dot = tk.Label(status_bar, text="●", font=("Segoe UI", 10),
                                   bg=bg, fg="#8b96ad")
        self.status_dot.pack(side="left")
        ttk.Label(status_bar, textvariable=self.status_var,
                  style="Muted.TLabel").pack(side="left", padx=(4, 0))
        ttk.Button(status_bar, text="Убить агент", style="Danger.TButton",
                   command=self.on_kill).pack(side="right")

    def _toggle_run(self):
        if self.running:
            self.on_stop()
        else:
            self._save()
            self.on_start()

    def _save(self):
        self.config_data["server_url"] = self.server_var.get().strip()
        try:
            self.config_data["poll_seconds"] = max(3, int(self.poll_var.get().strip() or "10"))
        except ValueError:
            self.config_data["poll_seconds"] = 10
        self.poll_var.set(str(self.config_data["poll_seconds"]))
        self.on_save()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for dev in self.config_data.get("devices", []):
            dtype = (dev.get("type") or "").lower()
            self.tree.insert("", "end", iid=dev["id"], values=(
                dev.get("name", ""),
                TYPE_LABELS.get(dtype, dtype),
                describe_device(dev),
                "",
            ))

    def _add_device(self, name, dtype, spec):
        if not name:
            return
        import uuid
        dev = {"id": str(uuid.uuid4()), "name": name, "type": dtype, "spec": spec}
        self.config_data.setdefault("devices", []).append(dev)
        self._refresh_tree()

    def _add_process(self):
        name = _ask_list_or_manual(self.root, "Процесс",
                                   "Выберите запущенный процесс:",
                                   checkers.list_running_processes())
        if name:
            self._add_device(name, "process", {"process_name": name})

    def _add_window(self):
        res = _ask_window(self.root)
        for item in res.get("items", []):
            self._add_device(item["name"], "window", item["spec"])

    def _add_com(self):
        port = _ask_list_or_manual(self.root, "COM-порт",
                                   "Выберите активный COM-порт:",
                                   checkers.list_com_ports())
        if port:
            self._add_device(port, "com", {"port": port})

    def _add_printer(self):
        name = _ask_list_or_manual(self.root, "Принтер",
                                   "Выберите принтер:",
                                   checkers.list_printers())
        if name:
            self._add_device(name, "printer", {"printer_name": name})

    def _add_rfid(self):
        res = _ask_rfid(self.root)
        if res and res.get("spec"):
            self._add_device(res["name"], "rfid", res["spec"])

    def _add_custom(self):
        res = _ask_custom(self.root)
        if res and res.get("spec"):
            self._add_device(res["name"], "custom", res["spec"])

    def _remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        ids = set(sel)
        self.config_data["devices"] = [d for d in self.config_data.get("devices", [])
                                       if d["id"] not in ids]
        self._refresh_tree()

    def _poll_queue(self):
        try:
            while True:
                self._handle_ui(self.ui_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _handle_ui(self, item):
        action = item.get("action")
        if action == "show":
            self.show()
        elif action == "exit":
            self.on_exit()
        elif action == "stop":
            self.on_stop()
        elif action == "results":
            self.update_results(item.get("results"))
        elif action == "status":
            self.status_var.set(item.get("text", ""))
            ok = item.get("ok", False)
            self.status_dot.config(fg="#22c55e" if ok else "#ef4444")
        elif action == "conn":
            self.set_connection(item.get("state"))
        elif action == "short_id":
            self.set_short_id(item.get("text", ""))
        elif action == "running":
            self.set_running(bool(item.get("running")))

    def set_connection(self, state):
        color, text = CONN.get(state, CONN["idle"])
        self.conn_dot.config(fg=color)
        self.conn_label.config(text=text)

    def set_short_id(self, sid):
        if sid:
            self.id_var.set("ID: " + sid)

    def set_running(self, running):
        self.running = running
        self.run_btn.config(text="Остановить" if running else "Запустить")
        self.run_btn.configure(style="TButton" if running else "Accent.TButton")
        if not running:
            self.set_connection("idle")
            self.status_var.set("")
            self.status_dot.config(fg="#8b96ad")

    def update_results(self, results):
        statuses = {}
        for r in (results or []):
            statuses[r.get("id")] = (r.get("status") == "ok", r.get("message", ""))
        for iid in self.tree.get_children():
            if iid in statuses:
                ok, msg = statuses[iid]
                self.tree.set(iid, "status", "OK" if ok else "ПРОБЛЕМА")

    def _on_close(self):
        self.on_close()

    def show(self):
        self.root.deiconify()
        self.root.wm_state("normal")
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(120, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def hide(self):
        self.root.iconify()

    def run(self):
        self.root.mainloop()

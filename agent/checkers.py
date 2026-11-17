import re
import socket
import subprocess
import sys
import time

import psutil

try:
    import serial.tools.list_ports
except Exception:
    serial = None

try:
    import win32print
except Exception:
    win32print = None

try:
    import win32gui
    import win32process
except Exception:
    win32gui = None
    win32process = None

try:
    import hid
except Exception:
    hid = None


def _parse_int(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    s = s[2:] if s.lower().startswith("0x") else s
    try:
        return int(s, 16)
    except ValueError:
        return None


def _normalize_process(name):
    n = (name or "").strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return n


def list_running_processes():
    seen = set()
    for p in psutil.process_iter(["name"]):
        try:
            name = p.info.get("name")
            if name and name.lower().endswith(".exe"):
                seen.add(name)
        except Exception:
            continue
    return sorted(seen)


def list_com_ports():
    if serial is None:
        return []
    return [p.device for p in serial.tools.list_ports.comports()]


def list_printers():
    if win32print is None:
        return []
    names = []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        for info in win32print.EnumPrinters(flags, None, 2):
            name = info.get("pPrinterName")
            if name:
                names.append(name)
    except Exception:
        pass
    return names


def list_hid_devices():
    if hid is None:
        return []
    out = []
    for d in hid.enumerate():
        label = "VID 0x%04x PID 0x%04x" % (d.get("vendor_id", 0), d.get("product_id", 0))
        if d.get("product_string"):
            label += " — " + d["product_string"]
        out.append(label)
    return out


def _iter_windows():
    if win32gui is None:
        return []
    results = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title.strip():
            return True
        proc = ""
        cmdline = ""
        wclass = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                p = psutil.Process(pid)
                proc = p.name() or ""
                cmdline = " ".join(p.cmdline())
        except Exception:
            pass
        try:
            wclass = win32gui.GetClassName(hwnd)
        except Exception:
            pass
        results.append({
            "title": title, "process": proc or "",
            "cmdline": cmdline or "", "class": wclass or "",
        })
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    return results


def list_windows():
    return _iter_windows()


def check_window(spec):
    title_sub = (spec.get("title") or "").strip().lower()
    process_filter = _normalize_process(spec.get("process") or "")
    cmdline_sub = (spec.get("cmdline") or "").strip().lower()
    if not (title_sub or process_filter or cmdline_sub):
        return False, "не заданы критерии окна"
    for w in _iter_windows():
        if process_filter and _normalize_process(w.get("process") or "") != process_filter:
            continue
        if title_sub and cmdline_sub:
            if not (title_sub in (w.get("title") or "").lower()
                    or cmdline_sub in (w.get("cmdline") or "").lower()):
                continue
        elif title_sub:
            if title_sub not in (w.get("title") or "").lower():
                continue
        elif cmdline_sub:
            if cmdline_sub not in (w.get("cmdline") or "").lower():
                continue
        return True, "окно открыто (%s)" % (w.get("title") or "")
    return False, "окно не найдено"


def check_process(spec):
    name = _normalize_process(spec.get("process_name", ""))
    if not name:
        return False, "не задано имя процесса"
    for p in psutil.process_iter(["name"]):
        try:
            pname = _normalize_process(p.info.get("name") or "")
            if pname == name:
                return True, "запущен (pid %s)" % p.pid
        except Exception:
            continue
    return False, "процесс не запущен"


def check_com(spec):
    port = (spec.get("port") or "").strip().upper()
    if not port:
        return False, "не задан порт"
    for p in (serial.tools.list_ports.comports() if serial else []):
        if (p.device or "").upper() == port:
            return True, "порт активен (%s)" % (p.description or "")
    return False, "порт %s не найден" % port


def check_printer(spec):
    name = (spec.get("printer_name") or "").strip()
    if not name:
        return False, "не задан принтер"
    if win32print is None:
        return False, "нет доступа к принтерам (не Windows)"
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        printers = win32print.EnumPrinters(flags, None, 2)
    except Exception as e:
        return False, "ошибка списка принтеров: %s" % e
    found = None
    for info in printers:
        if info.get("pPrinterName") == name:
            found = info
            break
    if found is None:
        return False, "принтер не найден"
    try:
        handle = win32print.OpenPrinter(name)
        try:
            info = win32print.GetPrinter(handle, 2)
            status = info.get("Status", 0)
            attributes = info.get("Attributes", 0)
        finally:
            win32print.ClosePrinter(handle)
    except Exception as e:
        return False, "принтер недоступен: %s" % e
    offline = getattr(win32print, "PRINTER_STATUS_OFFLINE", 0x80)
    work_offline = getattr(win32print, "PRINTER_ATTRIBUTE_WORK_OFFLINE", 0x400)
    if status & offline:
        return False, "принтер офлайн"
    if attributes & work_offline:
        return False, "принтер в режиме «работать автономно»"

    status_flags = [
        (getattr(win32print, "PRINTER_STATUS_PAPER_OUT", 0x10), "нет бумаги"),
        (getattr(win32print, "PRINTER_STATUS_PAPER_JAM", 0x08), "замятие бумаги"),
        (getattr(win32print, "PRINTER_STATUS_NO_TONER", 0x40000), "нет тонера"),
        (getattr(win32print, "PRINTER_STATUS_TONER_LOW", 0x20000), "мало тонера"),
        (getattr(win32print, "PRINTER_STATUS_DOOR_OPEN", 0x400000), "открыта крышка"),
        (getattr(win32print, "PRINTER_STATUS_OUTPUT_BIN_FULL", 0x800), "лоток заполнен"),
        (getattr(win32print, "PRINTER_STATUS_PAPER_PROBLEM", 0x40), "проблема с бумагой"),
        (getattr(win32print, "PRINTER_STATUS_MANUAL_FEED", 0x20), "ручная подача бумаги"),
    ]
    for flag, label in status_flags:
        if status & flag:
            return False, label

    error = getattr(win32print, "PRINTER_STATUS_ERROR", 0x02)
    paused = getattr(win32print, "PRINTER_STATUS_PAUSED", 0x01)
    if status & error:
        return False, "ошибка принтера"
    if status & paused:
        return False, "принтер на паузе"
    return True, "online"


def check_tcp(spec):
    host = (spec.get("host") or "").strip()
    port = spec.get("port")
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False, "не задан порт"
    s = socket.socket()
    s.settimeout(4)
    try:
        s.connect((host, port))
        return True, "%s:%s доступен" % (host, port)
    except Exception as e:
        return False, "%s:%s недоступен (%s)" % (host, port, e)
    finally:
        s.close()


def check_ping(spec):
    host = (spec.get("host") or "").strip()
    if not host:
        return False, "не задан хост"
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", "2000", host]
    else:
        cmd = ["ping", "-c", "1", "-W", "2", host]
    try:
        rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except Exception as e:
        return False, "ping ошибка: %s" % e
    if rc == 0:
        return True, "хост отвечает"
    return False, "хост не отвечает"


_usb_cache = {"ts": 0.0, "ids": []}


def _parse_hwid(spec):
    vid = _parse_int(spec.get("vid"))
    pid = _parse_int(spec.get("pid"))
    if vid is None or pid is None:
        raw = (spec.get("hwid") or spec.get("name") or "").strip().upper()
        m = re.search(r"VID_([0-9A-F]{4}).*?PID_([0-9A-F]{4})", raw)
        if m:
            vid = int(m.group(1), 16)
            pid = int(m.group(2), 16)
    return vid, pid


def _windows_usb_ids():
    if sys.platform != "win32":
        return []
    now = time.time()
    if now - _usb_cache["ts"] < 15:
        return _usb_cache["ids"]
    ids = []
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -PresentOnly | ForEach-Object { $_.InstanceId }"],
            capture_output=True, text=True, timeout=10, creationflags=flags)
        ids = [l.strip().upper() for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        pass
    _usb_cache["ts"] = now
    _usb_cache["ids"] = ids
    return ids


def check_usb_hid(spec):
    vid, pid = _parse_hwid(spec)
    name_sub = (spec.get("name") or "").strip().lower()
    if vid is not None and pid is not None:
        vh = "VID_%04X" % vid
        ph = "PID_%04X" % pid
        for iid in _windows_usb_ids():
            if vh in iid and ph in iid:
                return True, "устройство подключено (%s)" % iid
        if hid is not None:
            for d in hid.enumerate():
                if d.get("vendor_id") == vid and d.get("product_id") == pid:
                    return True, "найден (%s)" % (d.get("product_string") or "HID")
        return False, "устройство не найдено (VID_%04X PID_%04X)" % (vid, pid)
    if name_sub:
        if hid is None:
            return False, "нет доступа к HID"
        for d in hid.enumerate():
            if name_sub in (d.get("product_string") or "").lower():
                return True, "найден (%s)" % (d.get("product_string") or "HID")
    return False, "не заданы VID/PID или имя"


def check_rfid(spec):
    mode = (spec.get("mode") or "usb").lower()
    if mode == "com":
        return check_com({"port": spec.get("port")})
    if mode == "tcp":
        return check_tcp({"host": spec.get("host"), "port": spec.get("port")})
    return check_usb_hid(spec)


def check_custom(spec):
    t = (spec.get("check_type") or "").lower()
    if t == "tcp":
        return check_tcp(spec)
    if t == "ping":
        return check_ping(spec)
    if t == "usb":
        return check_usb_hid(spec)
    if t == "com":
        return check_com(spec)
    if t == "process":
        return check_process(spec)
    if t == "printer":
        return check_printer(spec)
    return False, "неизвестный тип проверки: %s" % t


def check_device(device):
    dtype = (device.get("type") or "").lower()
    spec = device.get("spec") or {}
    try:
        if dtype == "process":
            ok, msg = check_process(spec)
        elif dtype == "com":
            ok, msg = check_com(spec)
        elif dtype == "printer":
            ok, msg = check_printer(spec)
        elif dtype == "rfid":
            ok, msg = check_rfid(spec)
        elif dtype == "window":
            ok, msg = check_window(spec)
        elif dtype == "custom":
            ok, msg = check_custom(spec)
        else:
            ok, msg = False, "неизвестный тип: %s" % dtype
    except Exception as e:
        ok, msg = False, "ошибка проверки: %s" % e
    return ok, msg

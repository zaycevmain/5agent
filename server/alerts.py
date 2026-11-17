import logging
import os
import queue
import smtplib
import threading
from email.mime.text import MIMEText
from smtplib import SMTPAuthenticationError, SMTPServerDisconnected

import requests

import config as config_mod

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("5agent")

_alert_queue = queue.Queue()
_started = False


def _setup_logger():
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    try:
        fh = logging.FileHandler(os.path.join(BASE_DIR, "server.log"), encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass


def _send_telegram(text):
    cfg = config_mod.CONFIG["alerts"]["telegram"]
    token = cfg.get("bot_token")
    chat = cfg.get("chat_id")
    if not token or not chat:
        logger.warning("telegram: не задан bot_token или chat_id")
        return
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    proxies = None
    proxy = cfg.get("proxy", "")
    if proxy:
        proxies = {"http": proxy, "https": proxy}
    try:
        r = requests.post(url, json={"chat_id": chat, "text": text},
                          proxies=proxies, timeout=12)
        if r.status_code != 200:
            logger.error("telegram: HTTP %s %s", r.status_code, r.text[:300])
        else:
            logger.info("telegram sent")
    except Exception:
        logger.exception("telegram error")


def _send_email(subject, body):
    cfg = config_mod.CONFIG["alerts"]["email"]
    to = cfg.get("to") or []
    if not to:
        logger.warning("email: пустой список получателей to")
        return
    if not cfg.get("smtp_host"):
        logger.warning("email: не задан smtp_host")
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg.get("from") or cfg.get("username")
    msg["To"] = ", ".join(to)
    host = cfg["smtp_host"]
    port = int(cfg.get("smtp_port", 587))
    try:
        if cfg.get("use_tls", True):
            s = smtplib.SMTP(host, port, timeout=15)
            s.starttls()
        else:
            s = smtplib.SMTP_SSL(host, port, timeout=15)
        user = cfg.get("username")
        pwd = cfg.get("password")
        if user:
            s.login(user, pwd)
        s.sendmail(msg["From"], to, msg.as_string())
        s.quit()
        logger.info("email sent to %s", ", ".join(to))
    except SMTPAuthenticationError as e:
        logger.error("email: неверный логин/пароль (SMTP %s). Для Gmail нужен App Password "
                     "(Google → Безопасность → Пароли приложений), а не обычный пароль.", e.smtp_code)
    except SMTPServerDisconnected as e:
        logger.error("email: сервер закрыл соединение при авторизации (%s). "
                     "Обычно это неверный пароль — для Gmail нужен App Password.", e)
    except Exception:
        logger.exception("email error (%s:%s)", host, port)


def _notify(text):
    cfg = config_mod.CONFIG["alerts"]
    if cfg["telegram"].get("enabled"):
        _send_telegram(text)
    if cfg["email"].get("enabled"):
        _send_email("5agent alert", text)


def _worker():
    while True:
        evt = _alert_queue.get()
        try:
            kind = evt.get("kind")
            text = evt.get("text", "")
            if kind in ("device_down", "agent_offline"):
                _notify(text)
            elif kind in ("device_recovered", "agent_online"):
                if config_mod.CONFIG["alerts"].get("notify_on_recovery", True):
                    _notify(text)
        except Exception:
            logger.exception("worker error")


def ensure_worker():
    global _started
    if _started:
        return
    _started = True
    _setup_logger()
    threading.Thread(target=_worker, daemon=True).start()


def enqueue(transition):
    _alert_queue.put(transition)


def send_test():
    _notify("Тестовый алерт от 5agent")

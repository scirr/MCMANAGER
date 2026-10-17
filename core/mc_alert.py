"""
mc_alert.py — Alert channels (e-mail, Telegram, ntfy, generic webhook, extra
Discord webhooks) driven by server events.

Channels live in config.json under "alerts" (config.json is written 0600, so
tokens and passwords stay private). The historical "webhook_url" Discord
announcements are untouched; they are listed here as the "discord" channel so
that 'mc alert test' reaches them too.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import smtplib
import ssl
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from urllib.parse import urlparse

from mc_lang import T

EVENTS = ("start", "stop", "crash", "crash_loop", "backup_failed", "update", "sleep", "wake")
TYPES = ("email", "telegram", "ntfy", "webhook", "discord")
SECRET_FIELDS = ("password", "token", "secret")
TIMEOUT = 10
DEFAULT_NTFY = "https://ntfy.sh"
COLORS = {"start": 3066993, "wake": 3066993, "stop": 15158332, "crash": 15158332,
          "crash_loop": 15158332, "backup_failed": 15105570, "update": 3447003, "sleep": 9807270}
NTFY_PRIORITY = {"crash": "high", "crash_loop": "urgent", "backup_failed": "high"}


def parse_events(text):
    """'start,stop' / '*' / '' -> list of events, or None if one is unknown."""
    if text is None or str(text).strip() in ("", "*", "all"):
        return ["*"]
    wanted = [e.strip().lower() for e in str(text).split(",") if e.strip()]
    if any(e not in EVENTS for e in wanted):
        return None
    return list(dict.fromkeys(wanted))


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def valid_url(url):
    parts = urlparse(str(url))
    if not parts.hostname:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and _loopback(parts.hostname))


def validate(kind, params):
    """Returns an error code, or None when the channel parameters are usable."""
    if kind not in TYPES:
        return "bad_type"
    if kind == "email":
        if not params.get("host"):
            return "missing_host"
        if not params.get("sender") or not params.get("to"):
            return "missing_addresses"
        try:
            if not 0 < int(params.get("port", 587)) < 65536:
                return "bad_port"
        except (TypeError, ValueError):
            return "bad_port"
    elif kind == "telegram":
        if not params.get("token") or not params.get("chat_id"):
            return "missing_telegram"
    elif kind == "ntfy":
        if not params.get("topic"):
            return "missing_topic"
        if not valid_url(params.get("server") or DEFAULT_NTFY):
            return "bad_url"
    else:
        if not valid_url(params.get("url", "")):
            return "bad_url"
    return None


def channels(config):
    return [c for c in config.get("alerts", []) if isinstance(c, dict)]


def public(ch):
    """A channel as plain data that is safe to print: secrets masked, header
    values replaced by their names, webhook URLs cut after the host."""
    shown = {k: ("***" if k in SECRET_FIELDS and v else v) for k, v in ch.items() if k != "headers"}
    secrets = [k for k in SECRET_FIELDS if ch.get(k)]
    if ch.get("headers"):
        shown["header_names"] = sorted(ch["headers"])
        secrets.append("headers")
    if shown.get("url"):
        u = urlparse(shown["url"])
        shown["url"] = f"{u.scheme}://{u.netloc}/..."
    shown["secrets_set"] = secrets
    return shown


def listing(config):
    """Channels as plain data with every secret masked, the legacy Discord
    webhook included."""
    out = [public(ch) for ch in channels(config)]
    if config.get("webhook_url"):
        u = urlparse(config["webhook_url"])
        out.append({"name": "discord", "type": "discord", "events": ["*"], "legacy": True,
                    "url": f"{u.scheme}://{u.netloc}/...", "secrets_set": ["url"]})
    return out


def next_name(config, kind):
    taken = {c.get("name") for c in channels(config)} | {"discord"}
    if kind not in taken:
        return kind
    i = 2
    while f"{kind}-{i}" in taken:
        i += 1
    return f"{kind}-{i}"


def subscribed(channel, event):
    events = channel.get("events") or ["*"]
    return "*" in events or event in events


def build_event(event, server, reason=None, detail=None):
    reason_label = T.get(f"alert_reason_{reason}", reason) if reason else ""
    title = T[f"alert_title_{event}"].format(nom=server, reason=reason_label)
    message = T[f"alert_text_{event}"].format(nom=server, reason=reason_label)
    if detail:
        message = f"{message}\n{detail}"
    return {"event": event, "server": server, "reason": reason, "title": title,
            "message": message, "detail": detail or "", "time": int(time.time())}


# ── transports (module-level so tests substitute them) ──────────────────────

def http_post(url, body, headers):
    req = urllib.request.Request(url, data=body, headers=dict(headers, **{"User-Agent": "MCManagerBot/2.0"}),
                                 method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310 - scheme checked by valid_url
        resp.read(1024)


def smtp_connect(host, port):
    return smtplib.SMTP(host, port, timeout=TIMEOUT)


def _send_email(ch, doc):
    msg = EmailMessage()
    recipients = [a.strip() for a in ch["to"] if a.strip()] if isinstance(ch["to"], list) else \
        [a.strip() for a in str(ch["to"]).split(",") if a.strip()]
    msg["Subject"] = doc["title"]
    msg["From"] = ch["sender"]
    msg["To"] = ", ".join(recipients)
    msg.set_content(doc["message"])
    smtp = smtp_connect(ch["host"], int(ch.get("port", 587)))
    try:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        if ch.get("user"):
            smtp.login(ch["user"], ch.get("password", ""))
        smtp.send_message(msg, from_addr=ch["sender"], to_addrs=recipients)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass


def _send_telegram(ch, doc):
    url = f"https://api.telegram.org/bot{ch['token']}/sendMessage"
    body = json.dumps({"chat_id": ch["chat_id"], "text": f"{doc['title']}\n{doc['message']}"}).encode()
    http_post(url, body, {"Content-Type": "application/json"})


def _header_text(text):
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


def _send_ntfy(ch, doc):
    base = (ch.get("server") or DEFAULT_NTFY).rstrip("/")
    headers = {"Title": _header_text(doc["title"]),
               "Tags": doc["event"], "Content-Type": "text/plain; charset=utf-8"}
    if doc["event"] in NTFY_PRIORITY:
        headers["Priority"] = NTFY_PRIORITY[doc["event"]]
    if ch.get("token"):
        headers["Authorization"] = f"Bearer {ch['token']}"
    http_post(f"{base}/{urllib.parse.quote(ch['topic'], safe='')}", doc["message"].encode("utf-8"), headers)


def _send_webhook(ch, doc):
    body = json.dumps({"schema": 1, **doc}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(ch.get("headers") or {})
    if ch.get("secret"):
        headers["X-MCManager-Signature"] = "sha256=" + hmac.new(ch["secret"].encode(), body, hashlib.sha256).hexdigest()
    http_post(ch["url"], body, headers)


def _send_discord(ch, doc):
    embed = {"title": doc["title"], "description": doc["message"], "color": COLORS.get(doc["event"], 0)}
    http_post(ch["url"], json.dumps({"embeds": [embed]}).encode("utf-8"), {"Content-Type": "application/json"})


_SENDERS = {"email": _send_email, "telegram": _send_telegram, "ntfy": _send_ntfy,
            "webhook": _send_webhook, "discord": _send_discord}


def _redact(text, ch):
    for field in SECRET_FIELDS:
        if ch.get(field):
            text = text.replace(str(ch[field]), "***")
    for value in (ch.get("headers") or {}).values():
        if value:
            text = text.replace(str(value), "***")
    if ch.get("url"):
        text = text.replace(str(ch["url"]), public(ch)["url"])
    return text


def send(ch, doc):
    """(ok, detail) for one channel. Never raises."""
    if ch.get("legacy"):
        ch = {"type": "discord", "url": ch["url"]}
    try:
        _SENDERS[ch["type"]](ch, doc)
        return True, "OK"
    except Exception as e:
        return False, _redact(f"{type(e).__name__}: {e}", ch)


def notify(config, event, force=False, **info):
    """Send `event` to every subscribed channel. Silent during maintenance
    (like the Discord announcements) unless forced. Returns
    [(channel name, ok, detail)]; a failing channel never affects the caller."""
    try:
        if event not in EVENTS or not channels(config):
            return []
        if not force and config.get("mode_maintenance", 0) == 1:
            return []
        doc = build_event(event, config.get("nom_serveur", "Minecraft"), info.get("reason"), info.get("detail"))
        done = []
        for ch in channels(config):
            if not subscribed(ch, event):
                continue
            ok, detail = send(ch, doc)
            if not ok:
                logging.warning(f"Alert channel {ch.get('name')} failed: {detail}")
            done.append((ch.get("name"), ok, detail))
        return done
    except Exception as e:
        logging.warning(f"Alert dispatch failed: {e}")
        return []


def test_channels(config, name=None):
    """Send a test message to one channel (or all, legacy Discord included),
    ignoring event filters. Returns (found, [(name, ok, detail)])."""
    pool = channels(config) + ([{"name": "discord", "type": "discord", "legacy": True,
                                 "url": config["webhook_url"]}] if config.get("webhook_url") else [])
    if name:
        pool = [c for c in pool if c.get("name") == name]
        if not pool:
            return False, []
    doc = build_event("start", config.get("nom_serveur", "Minecraft"))
    doc.update(title=T["alert_test_title"].format(nom=doc["server"]), message=T["alert_test_text"], event="test")
    return True, [(c.get("name"), *send(c, doc)) for c in pool]

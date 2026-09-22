#!/usr/bin/env python3
"""
Watchdog тоннеля для tg-poll-tagbot.

Раз в несколько минут проверяет, ходит ли трафик до Telegram через SOCKS-прокси
(Xray). Если нет — тянет свежий список серверов из ссылки-подписки, перебирает
их, переключает Xray на первый рабочий и перезапускает бота.

Владельцу пишет в Telegram через Bot API НАПРЯМУЮ (api.telegram.org с YC-ВМ
доступен без тоннеля) — поэтому уведомление дойдёт, даже когда тоннель мёртв.

Запускается от root по systemd-таймеру. Ничего не делает, пока тоннель живой.
"""

import base64
import binascii
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

XRAY_CONFIG = "/usr/local/etc/xray/config.json"
SUB_URL_FILE = "/usr/local/etc/xray/subscription.url"   # root-only, 0600
FALLBACK_NODES_FILE = "/usr/local/etc/xray/fallback-nodes.txt"  # root-only, 0600
STATE_FILE = "/var/lib/tg-poll-tagbot-watchdog.json"
BOT_ENV = "/home/yc-user/tg-poll-tagbot/.env"
SOCKS = "127.0.0.1:10808"
PROBE_URL = "https://api.telegram.org/"
BOTAPI_IP = "149.154.167.220"  # DNS отдаёт заблокированный адрес, этот доступен с YC
ALERT_COOLDOWN = 3600          # не чаще раза в час напоминать о поломке
CHECK_TIMEOUT = 12


def log(msg):
    print(f"[watchdog] {msg}", flush=True)


# ---------- парсинг подписки (чистая логика, покрыта тестами) ----------

def decode_subscription(raw):
    """Тело подписки → список vless://-строк. Поддерживает base64 и plain text."""
    text = (raw or "").strip()
    if not text:
        return []
    if "://" not in text:
        try:
            padded = text + "=" * (-len(text) % 4)
            text = base64.b64decode(padded).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            return []
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("vless://")]


def parse_json_config(cfg):
    """Готовый Xray-конфиг из JSON-подписки (формат Happ) → dict ноды или None."""
    if not isinstance(cfg, dict):
        return None
    for out in cfg.get("outbounds", []):
        if out.get("protocol") != "vless":
            continue
        stream = out.get("streamSettings", {})
        reality = stream.get("realitySettings", {})
        if stream.get("security") != "reality" or stream.get("network", "tcp") != "tcp":
            continue
        vnext = (out.get("settings", {}).get("vnext") or [{}])[0]
        user = (vnext.get("users") or [{}])[0]
        if not vnext.get("address") or not user.get("id") or not reality.get("publicKey"):
            continue
        return {
            "address": vnext["address"],
            "port": vnext.get("port", 443),
            "uuid": user["id"],
            "public_key": reality["publicKey"],
            "server_name": reality.get("serverName", vnext["address"]),
            "short_id": reality.get("shortId", ""),
            "fingerprint": reality.get("fingerprint", "chrome"),
            "flow": user.get("flow", "xtls-rprx-vision"),
            "remark": cfg.get("remarks") or vnext["address"],
        }
    return None


def parse_subscription(raw):
    """Тело подписки → список нод. Понимает JSON-конфиги (Happ) и vless://-списки."""
    text = (raw or "").strip()
    if text.startswith(("[", "{")):
        try:
            data = json.loads(text)
        except ValueError:
            return []
        configs = data if isinstance(data, list) else [data]
        return [n for n in (parse_json_config(c) for c in configs) if n]
    return [n for n in (parse_vless(u) for u in decode_subscription(text)) if n]


def parse_vless(uri):
    """vless://uuid@host:port?params#remark → dict для конфига Xray (или None).

    Берём только TCP+Reality — именно такие ноды у нашего провайдера.
    """
    if not uri.startswith("vless://"):
        return None
    parsed = urllib.parse.urlparse(uri)
    if not parsed.hostname or not parsed.username:
        return None
    q = urllib.parse.parse_qs(parsed.query)

    def first(key, default=""):
        return q.get(key, [default])[0]

    if first("security") != "reality" or first("type", "tcp") != "tcp":
        return None
    pbk, sni = first("pbk"), first("sni")
    if not pbk or not sni:
        return None
    return {
        "address": parsed.hostname,
        "port": parsed.port or 443,
        "uuid": parsed.username,
        "public_key": pbk,
        "server_name": sni,
        "short_id": first("sid"),
        "fingerprint": first("fp", "chrome"),
        "flow": first("flow", "xtls-rprx-vision"),
        "remark": urllib.parse.unquote(parsed.fragment or parsed.hostname),
    }


def build_config(node):
    """dict ноды → конфиг Xray (SOCKS-инбаунд + VLESS/Reality-аутбаунд)."""
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": 10808,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
            "tag": "socks",
        }],
        "outbounds": [{
            "protocol": "vless",
            "settings": {"vnext": [{
                "address": node["address"],
                "port": node["port"],
                "users": [{
                    "id": node["uuid"],
                    "encryption": "none",
                    "flow": node["flow"],
                }],
            }]},
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "fingerprint": node["fingerprint"],
                    "publicKey": node["public_key"],
                    "serverName": node["server_name"],
                    "shortId": node["short_id"],
                },
            },
            "tag": "proxy",
        }],
    }


def current_node_address(path=XRAY_CONFIG):
    try:
        with open(path) as fh:
            cfg = json.load(fh)
        return cfg["outbounds"][0]["settings"]["vnext"][0]["address"]
    except Exception:
        return "?"


# ---------- работа с системой ----------

def tunnel_alive():
    """Проходит ли трафик до Telegram через SOCKS."""
    try:
        out = subprocess.run(
            ["curl", "-sS", "-m", str(CHECK_TIMEOUT), "--socks5-hostname", SOCKS,
             "-o", "/dev/null", "-w", "%{http_code}", PROBE_URL],
            capture_output=True, text=True, timeout=CHECK_TIMEOUT + 5,
        ).stdout.strip()
        return out in ("200", "301", "302")
    except Exception:
        return False


def fetch_subscription():
    nodes = []
    try:
        with open(SUB_URL_FILE) as fh:
            url = fh.read().strip()
        if url:
            req = urllib.request.Request(url, headers={"User-Agent": "Happ/1 (watchdog)"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                nodes = parse_subscription(resp.read().decode("utf-8", "replace"))
    except FileNotFoundError:
        pass
    except Exception as exc:
        log(f"не смог скачать подписку: {exc}")

    # Частная копия рабочих нод на ВМ: без секретов в Git и без зависимости от
    # доступности URL подписки. Пробуем её также при устаревшей подписке.
    try:
        with open(FALLBACK_NODES_FILE) as fh:
            fallback = parse_subscription(fh.read())
    except FileNotFoundError:
        fallback = []
    except OSError as exc:
        log(f"не смог прочитать резервные ноды: {exc}")
        fallback = []

    seen = set()
    unique = []
    for node in [*fallback, *nodes]:
        identity = (node["address"], node["port"], node["uuid"],
                    node["public_key"], node["short_id"])
        if identity not in seen:
            seen.add(identity)
            unique.append(node)
    log(f"годных нод: резерв={len(fallback)}, подписка={len(nodes)}, всего={len(unique)}")
    return unique


def apply_node(node):
    """Переключить Xray на ноду и проверить, ожил ли тоннель."""
    with open(XRAY_CONFIG, "w") as fh:
        json.dump(build_config(node), fh, indent=2)
    subprocess.run(["systemctl", "restart", "xray"], check=False)
    time.sleep(4)
    return tunnel_alive()


def notify(text):
    """Сообщение владельцу через Bot API напрямую (без тоннеля)."""
    token = owner = None
    try:
        with open(BOT_ENV) as fh:
            for line in fh:
                key, _, value = line.strip().partition("=")
                if key == "BOT_TOKEN":
                    token = value
                elif key == "OWNER_ID":
                    owner = value
    except OSError:
        return
    if not token or not owner:
        return
    # Пробуем по очереди: через тоннель (если жив), затем напрямую с пиннингом на
    # доступный IP Bot API (DNS отдаёт заблокированный адрес), затем как есть.
    for transport in (
        ["--socks5-hostname", SOCKS],
        ["--resolve", f"api.telegram.org:443:{BOTAPI_IP}"],
        [],
    ):
        try:
            res = subprocess.run(
                ["curl", "-4", "-sS", "-m", "15", *transport,
                 f"https://api.telegram.org/bot{token}/sendMessage",
                 "--data-urlencode", f"chat_id={owner}",
                 "--data-urlencode", f"text={text}"],
                capture_output=True, text=True, timeout=25,
            )
        except Exception:
            continue
        if '"ok":true' in res.stdout:
            return
        if '"ok":false' in res.stdout:      # достучались, но Telegram отказал
            log(f"уведомление отклонено: {res.stdout.strip()[:200]}")
            return
    log("уведомление не доставлено ни одним способом")


def load_state():
    try:
        with open(STATE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def main():
    if tunnel_alive():
        state = load_state()
        if state.get("broken"):           # починился сам — снимаем флаг
            save_state({})
        return 0

    log(f"тоннель мёртв (нода {current_node_address()}), ищу замену…")
    state = load_state()
    now = int(time.time())

    for node in fetch_subscription():
        if apply_node(node):
            log(f"переключился на {node['remark']} ({node['address']})")
            subprocess.run(["systemctl", "restart", "tg-poll-tagbot"], check=False)
            save_state({})
            notify(f"Тоннель падал — переключился на {node['remark']}. Бот снова работает.")
            return 0
        log(f"нода {node['address']} не подошла")

    log("рабочих нод не нашлось")
    if now - int(state.get("alerted_at", 0)) > ALERT_COOLDOWN:
        notify(
            "Тоннель до Telegram лежит, рабочих серверов в подписке нет. "
            "Проверь подписку VPN (возможно, истекла) — бот пока не отвечает на команды."
        )
        save_state({"broken": True, "alerted_at": now})
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Тесты парсера подписки и сборки конфига для xray-watchdog."""

import base64
import importlib.util
import io
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "xray_watchdog", Path(__file__).resolve().parent.parent / "deploy" / "xray_watchdog.py"
)
wd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wd)

VLESS = (
    "vless://11111111-2222-3333-4444-555555555555@node.example.com:443"
    "?type=tcp&security=reality&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "&fp=firefox&sni=node.example.com&sid=0123456789abcdef"
    "&flow=xtls-rprx-vision#Example-01"
)


# ---------- decode_subscription ----------

def test_decode_plain_text():
    raw = VLESS + "\n" + VLESS
    assert decode_len(raw) == 2


def decode_len(raw):
    return len(wd.decode_subscription(raw))


def test_decode_base64():
    raw = base64.b64encode((VLESS + "\n" + VLESS).encode()).decode()
    assert decode_len(raw) == 2


def test_decode_base64_without_padding():
    body = base64.b64encode(VLESS.encode()).decode().rstrip("=")
    assert decode_len(body) == 1


def test_decode_empty():
    assert wd.decode_subscription("") == []
    assert wd.decode_subscription(None) == []


def test_decode_garbage():
    assert wd.decode_subscription("не base64 и не ссылки") == []


def test_decode_skips_non_vless_lines():
    raw = "ss://something\n" + VLESS + "\n# comment"
    assert decode_len(raw) == 1


# ---------- parse_vless ----------

def test_parse_full():
    n = wd.parse_vless(VLESS)
    assert n["address"] == "node.example.com"
    assert n["port"] == 443
    assert n["uuid"] == "11111111-2222-3333-4444-555555555555"
    assert n["public_key"] == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert n["short_id"] == "0123456789abcdef"
    assert n["server_name"] == "node.example.com"
    assert n["fingerprint"] == "firefox"
    assert n["flow"] == "xtls-rprx-vision"
    assert n["remark"] == "Example-01"


def test_parse_urlencoded_remark():
    uri = VLESS.replace("#Example-01", "#%D0%93%D0%B5%D1%80%D0%BC%D0%B0%D0%BD%D0%B8%D1%8F")
    assert wd.parse_vless(uri)["remark"] == "Германия"


def test_parse_rejects_non_reality():
    assert wd.parse_vless(VLESS.replace("security=reality", "security=tls")) is None


def test_parse_rejects_non_tcp():
    assert wd.parse_vless(VLESS.replace("type=tcp", "type=ws")) is None


def test_parse_rejects_without_pbk():
    uri = VLESS.replace("&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "")
    assert wd.parse_vless(uri) is None


def test_parse_rejects_other_scheme():
    assert wd.parse_vless("ss://whatever@host:443") is None


def test_parse_defaults_fingerprint():
    uri = VLESS.replace("&fp=firefox", "")
    assert wd.parse_vless(uri)["fingerprint"] == "chrome"


# ---------- parse_subscription: JSON-формат (Happ) ----------

def _happ_config(remark="Example-01", address="node.example.com"):
    return {
        "remarks": remark,
        "dns": {"servers": [{"address": "1.1.1.1"}]},
        "inbounds": [{"port": 10808, "protocol": "socks"}],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {"vnext": [{
                    "address": address, "port": 443,
                    "users": [{"id": "11111111-2222-3333-4444-555555555555",
                               "encryption": "none", "flow": "xtls-rprx-vision"}],
                }]},
                "streamSettings": {
                    "network": "tcp", "security": "reality",
                    "realitySettings": {
                        "fingerprint": "firefox",
                        "publicKey": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                        "serverName": address, "shortId": "0123456789abcdef",
                    },
                },
                "tag": "proxy",
            },
            {"protocol": "freedom", "tag": "direct"},
        ],
    }


def test_parse_subscription_json_array():
    import json
    raw = json.dumps([_happ_config(), _happ_config("Backup-01", "backup.example.com")])
    nodes = wd.parse_subscription(raw)
    assert [n["remark"] for n in nodes] == ["Example-01", "Backup-01"]
    assert nodes[1]["address"] == "backup.example.com"


def test_parse_subscription_single_json_object():
    import json
    nodes = wd.parse_subscription(json.dumps(_happ_config()))
    assert len(nodes) == 1
    assert nodes[0]["public_key"] == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert nodes[0]["flow"] == "xtls-rprx-vision"


def test_parse_subscription_still_handles_vless_list():
    assert len(wd.parse_subscription(VLESS)) == 1


def test_parse_subscription_broken_json():
    assert wd.parse_subscription("[{broken") == []


def test_parse_json_config_skips_non_reality():
    cfg = _happ_config()
    cfg["outbounds"][0]["streamSettings"]["security"] = "tls"
    assert wd.parse_json_config(cfg) is None


def test_parse_json_config_skips_without_vless():
    cfg = _happ_config()
    cfg["outbounds"] = [{"protocol": "freedom", "tag": "direct"}]
    assert wd.parse_json_config(cfg) is None


def test_parse_json_config_falls_back_to_address_as_remark():
    cfg = _happ_config()
    del cfg["remarks"]
    assert wd.parse_json_config(cfg)["remark"] == "node.example.com"


def test_parse_json_config_rejects_non_dict():
    assert wd.parse_json_config("строка") is None


def test_json_node_builds_valid_config():
    node = wd.parse_json_config(_happ_config())
    cfg = wd.build_config(node)
    assert cfg["outbounds"][0]["settings"]["vnext"][0]["address"] == "node.example.com"


# ---------- build_config ----------

def test_build_config_shape():
    cfg = wd.build_config(wd.parse_vless(VLESS))
    inbound = cfg["inbounds"][0]
    assert (inbound["port"], inbound["protocol"], inbound["listen"]) == (10808, "socks", "127.0.0.1")
    out = cfg["outbounds"][0]
    assert out["protocol"] == "vless"
    vnext = out["settings"]["vnext"][0]
    assert vnext["address"] == "node.example.com"
    assert vnext["users"][0]["id"] == "11111111-2222-3333-4444-555555555555"
    reality = out["streamSettings"]["realitySettings"]
    assert reality["publicKey"] == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert reality["shortId"] == "0123456789abcdef"


def test_build_config_is_json_serializable(tmp_path):
    import json
    cfg = wd.build_config(wd.parse_vless(VLESS))
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cfg))
    assert json.loads(p.read_text())["outbounds"][0]["tag"] == "proxy"


def test_current_node_address_reads_config(tmp_path):
    import json
    cfg = wd.build_config(wd.parse_vless(VLESS))
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    assert wd.current_node_address(str(p)) == "node.example.com"


def test_current_node_address_missing_file(tmp_path):
    assert wd.current_node_address(str(tmp_path / "nope.json")) == "?"


def test_fetch_subscription_uses_private_fallback_when_url_missing(tmp_path, monkeypatch):
    fallback = tmp_path / "fallback-nodes.txt"
    fallback.write_text(VLESS)
    monkeypatch.setattr(wd, "SUB_URL_FILE", str(tmp_path / "missing.url"))
    monkeypatch.setattr(wd, "FALLBACK_NODES_FILE", str(fallback))
    assert [n["address"] for n in wd.fetch_subscription()] == ["node.example.com"]


def test_fetch_subscription_prioritizes_fallback_over_live_nodes(tmp_path, monkeypatch):
    url = tmp_path / "subscription.url"
    url.write_text("https://example.com/nodes")
    fallback = tmp_path / "fallback-nodes.txt"
    fallback.write_text(VLESS.replace("node.example.com", "backup.example.com"))
    monkeypatch.setattr(wd, "SUB_URL_FILE", str(url))
    monkeypatch.setattr(wd, "FALLBACK_NODES_FILE", str(fallback))
    monkeypatch.setattr(wd.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(VLESS.encode()))
    assert [n["address"] for n in wd.fetch_subscription()] == [
        "backup.example.com", "node.example.com"
    ]


def test_fetch_subscription_deduplicates_same_node(tmp_path, monkeypatch):
    url = tmp_path / "subscription.url"
    url.write_text("https://example.com/nodes")
    fallback = tmp_path / "fallback-nodes.txt"
    fallback.write_text(VLESS)
    monkeypatch.setattr(wd, "SUB_URL_FILE", str(url))
    monkeypatch.setattr(wd, "FALLBACK_NODES_FILE", str(fallback))
    monkeypatch.setattr(wd.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(VLESS.encode()))
    assert len(wd.fetch_subscription()) == 1

import base64
import io
import ipaddress
import pathlib
import re

import qrcode
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)

import config
from mikrotik import connect


class WGError(Exception):
    pass


def _gen_keypair():
    priv = X25519PrivateKey.generate()
    priv_b64 = base64.b64encode(
        priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    ).decode()
    pub_b64 = base64.b64encode(
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    return priv_b64, pub_b64


def _fetch(api):
    rows = api("/interface/wireguard/peers/print")
    peers = []
    for r in rows:
        if r.get("interface") != config.WG_INTERFACE:
            continue
        handshake = r.get("last-handshake") or ""
        if handshake in ("00:00:00", ""):
            handshake = ""
        peers.append(
            {
                "id": r.get(".id"),
                "name": (r.get("comment") or r.get("name") or "").strip(),
                "public_key": r.get("public-key") or "",
                "address": _fmt_addr(r.get("allowed-address")),
                "disabled": bool(r.get("disabled", False)),
                "handshake": handshake,
            }
        )
    return peers


def _fmt_addr(addr):
    if isinstance(addr, list):
        parts = []
        for a in addr:
            if isinstance(a, dict):
                parts.append(str(a.get("value", a.get("key"))))
            else:
                parts.append(str(a))
        return ", ".join(parts)
    return addr or "—"


def get_server_public_key(api):
    for r in api("/interface/wireguard/print"):
        if r.get("name") == config.WG_INTERFACE:
            pk = r.get("public-key")
            if not pk:
                raise WGError("У интерфейса нет публичного ключа")
            return pk
    raise WGError(f"Интерфейс '{config.WG_INTERFACE}' не найден на роутере")


def _used_ips(peers):
    used = set()
    for p in peers:
        for chunk in str(p["address"]).split(","):
            chunk = chunk.strip()
            try:
                used.add(ipaddress.ip_interface(chunk).ip)
            except ValueError:
                continue
    return used


def _next_free_ip(used):
    net = ipaddress.ip_network(config.WG_SUBNET)
    server = ipaddress.ip_address(config.WG_SERVER_ADDRESS)
    for ip in net.hosts():
        if ip == server:
            continue
        if ip not in used:
            return ip
    raise WGError("Нет свободных IP в подсети")


def _client_config(priv_b64, client_ip, server_pub):
    return (
        "[Interface]\n"
        f"PrivateKey = {priv_b64}\n"
        f"Address = {client_ip}/32\n"
        f"DNS = {config.WG_DNS}\n\n"
        "[Peer]\n"
        f"PublicKey = {server_pub}\n"
        f"Endpoint = {config.WG_ENDPOINT}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        "PersistentKeepalive = 25\n"
    )


def _make_qr(data):
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


CONFIGS_DIR = pathlib.Path(__file__).resolve().parent / "configs"


def _save_config(name, cfg):
    CONFIGS_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
    (CONFIGS_DIR / f"{safe}.conf").write_text(cfg, encoding="utf-8")


def get_peer_config(name):
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
    path = CONFIGS_DIR / f"{safe}.conf"
    if not path.exists():
        raise WGError(f"Настройки для '{name}' не найдены")
    return path.read_text(encoding="utf-8")


def list_peers():
    api = connect()
    try:
        return _fetch(api)
    finally:
        api.close()


def _fmt_bytes(n):
    n = int(n or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024


def peer_stats():
    api = connect()
    try:
        rows = api("/interface/wireguard/peers/print")
        stats = []
        for r in rows:
            if r.get("interface") != config.WG_INTERFACE:
                continue
            handshake = r.get("last-handshake") or ""
            if handshake in ("00:00:00", ""):
                handshake = ""
            ep = r.get("current-endpoint-address") or ""
            port = r.get("current-endpoint-port") or 0
            stats.append(
                {
                    "name": (r.get("comment") or r.get("name") or "").strip(),
                    "address": _fmt_addr(r.get("allowed-address")),
                    "rx": int(r.get("rx") or 0),
                    "tx": int(r.get("tx") or 0),
                    "handshake": handshake,
                    "endpoint": f"{ep}:{port}" if ep else "",
                    "disabled": bool(r.get("disabled", False)),
                }
            )
        return stats
    finally:
        api.close()


def server_status():
    api = connect()
    try:
        pub = get_server_public_key(api)
        peers = _fetch(api)
        enabled = sum(1 for p in peers if not p["disabled"])
        return {
            "public_key": pub,
            "total": len(peers),
            "enabled": enabled,
            "disabled": len(peers) - enabled,
        }
    finally:
        api.close()


def create_peer(name):
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,24}", name):
        raise WGError("Имя: только буквы, цифры, точки, дефис и _ (до 24 символов)")
    priv_b64, pub_b64 = _gen_keypair()
    api = connect()
    try:
        server_pub = get_server_public_key(api)
        peers = _fetch(api)
        if any(p["name"].lower() == name.lower() for p in peers):
            raise WGError(f"Пользователь '{name}' уже существует")
        client_ip = str(_next_free_ip(_used_ips(peers)))
        tuple(
            api(
                "/interface/wireguard/peers/add",
                interface=config.WG_INTERFACE,
                **{"public-key": pub_b64, "allowed-address": f"{client_ip}/32"},
                comment=name,
            )
        )
        cfg = _client_config(priv_b64, client_ip, server_pub)
        _save_config(name, cfg)
        return cfg, _make_qr(cfg)
    finally:
        api.close()


def set_disabled(name, disabled):
    api = connect()
    try:
        peers = _fetch(api)
        peer = next((p for p in peers if p["name"].lower() == name.lower()), None)
        if not peer:
            raise WGError(f"Пользователь '{name}' не найден")
        tuple(
            api(
                "/interface/wireguard/peers/set",
                **{".id": peer["id"], "disabled": "yes" if disabled else "no"},
            )
        )
    finally:
        api.close()


def remove_peer(name):
    api = connect()
    try:
        peers = _fetch(api)
        peer = next((p for p in peers if p["name"].lower() == name.lower()), None)
        if not peer:
            raise WGError(f"Пользователь '{name}' не найден")
        tuple(api("/interface/wireguard/peers/remove", **{".id": peer["id"]}))
    finally:
        api.close()

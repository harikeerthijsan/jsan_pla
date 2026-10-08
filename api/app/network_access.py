"""Office-network policy: users may be limited to listed networks; admins and users with remote access are exempt.

Behind Railway the client address comes from the edge proxy's ``X-Real-IP`` header. The left-most
``X-Forwarded-For`` entry is not used because a client can set it. Locally the direct socket address is used.
``CLIENT_IP_HEADER`` names a different trusted header when deployed elsewhere.
"""
from __future__ import annotations

import ipaddress
import json
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import AppSetting, User

POLICY_KEY = "user_network_policy"
MAX_NETWORKS = 50


def trusted_ip_header() -> str | None:
    header = os.getenv("CLIENT_IP_HEADER")
    if header is not None:
        return header.strip() or None
    return "X-Real-IP" if os.getenv("RAILWAY_ENVIRONMENT_NAME") else None


def client_ip(request) -> str | None:
    """The caller's address as the server sees it, or None when it cannot be trusted or parsed."""
    header = trusted_ip_header()
    if header:
        raw = request.headers.get(header)
        if not raw:  # behind a proxy, a request without the proxy's header is not trusted
            return None
    else:
        raw = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(raw.split(",")[0].strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


def get_network_policy(db: Session) -> dict:
    row = db.query(AppSetting).filter_by(key=POLICY_KEY).first()
    data = json.loads(row.value_json) if row else {}
    return {"enabled": bool(data.get("enabled")), "networks": list(data.get("networks") or []),
            "updated_by": row.updated_by if row else None,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


def normalise_networks(networks: list[dict]) -> list[dict]:
    """Validate and canonicalise {cidr, label} entries; raises ValueError with a user-facing message."""
    if len(networks) > MAX_NETWORKS:
        raise ValueError(f"List at most {MAX_NETWORKS} networks")
    out, seen = [], set()
    behind_proxy = trusted_ip_header() is not None
    for entry in networks:
        text = str(entry.get("cidr", "")).strip()
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as exc:
            raise ValueError(f"“{text}” is not an IP address or network (e.g. 203.0.113.7 or 203.0.113.0/24)") from exc
        if behind_proxy and (network.is_private or network.is_loopback or network.is_link_local):
            raise ValueError(f"{network} is a private office (LAN) address. The server only sees your office's public "
                             "address — open this page from the office and use “Add my current network”.")
        label = str(entry.get("label") or "").strip()[:80]
        if str(network) not in seen:
            seen.add(str(network))
            out.append({"cidr": str(network), "label": label})
    return out


def set_network_policy(db: Session, enabled: bool, networks: list[dict], actor: str) -> dict:
    clean = normalise_networks(networks)
    if enabled and not clean:
        raise ValueError("Add at least one office network before limiting users to it")
    row = db.query(AppSetting).filter_by(key=POLICY_KEY).first() or AppSetting(key=POLICY_KEY)
    row.value_json = json.dumps({"enabled": bool(enabled), "networks": clean})
    row.updated_by, row.updated_at = actor, datetime.now(timezone.utc)
    db.add(row)
    return {"enabled": bool(enabled), "networks": clean}


def ip_on_listed_network(ip: str | None, networks: list[dict]) -> bool:
    if not ip:
        return False
    address = ipaddress.ip_address(ip)
    return any(address in ipaddress.ip_network(n["cidr"], strict=False) for n in networks)


def user_network_allowed(db: Session, user: User, ip: str | None) -> bool:
    # Super admins are never restricted. Admins and users follow their own "anywhere" switch, which a
    # super admin (for admins) or an admin (for users) controls; existing admins were migrated to "anywhere".
    if (user.role or "").strip().upper() == "SUPER_ADMIN" or user.remote_access:
        return True
    policy = get_network_policy(db)
    return not policy["enabled"] or ip_on_listed_network(ip, policy["networks"])

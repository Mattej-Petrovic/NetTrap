from __future__ import annotations

import ipaddress


def is_private_ip(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def format_ip(ip: str) -> str:
    try:
        return str(ipaddress.ip_address(ip.strip()))
    except ValueError:
        return ip.strip()


def resolve_bind_host(host: str | None, default: str = "127.0.0.1") -> str:
    candidate = (host or "").strip()
    if not candidate:
        return default
    if candidate.lower() == "localhost":
        return "127.0.0.1"

    try:
        address = ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise ValueError(
            "Bind host must be localhost, 0.0.0.0, 127.0.0.1, or another IPv4 address."
        ) from exc

    if address.version != 4:
        raise ValueError("Bind host must be an IPv4 address or localhost.")
    return str(address)

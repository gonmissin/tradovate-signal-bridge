"""Read ``assets/config.json`` (order + connection) for Flask and the terminal client."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "assets" / "config.json"

# TV bridge market POST requires bid/ask fields; values are placeholders only (not live data).
TV_BRIDGE_BID_ASK: dict[str, tuple[float, float]] = {
    "nq": (23753.5, 23754.0),
    "gc": (4419.8, 4420.3),
}


def tv_bridge_placeholder_bid_ask(family: str) -> tuple[float, float]:
    """Return static ``(bid, ask)`` for family ``nq`` or ``gc`` (edit ``TV_BRIDGE_BID_ASK`` to change)."""
    fam = family.strip().lower()
    pair = TV_BRIDGE_BID_ASK.get(fam)
    if pair is None:
        raise ValueError(f"Unknown quote family {family!r} — expected nq or gc.")
    return float(pair[0]), float(pair[1])


def _data() -> dict:
    try:
        with CONFIG_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def connection_section() -> dict:
    return _data().get("connection") or {}


def order_section() -> dict:
    return _data().get("order") or {}


def developer_mode() -> bool:
    """When True, print full JSON bodies for API/auth responses (see assets/config.json)."""
    v = _data().get("developer_mode")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return False


def order_bool(key: str, default: bool) -> bool:
    """Read a boolean from ``order.<key>`` in config (bool, or string yes/no)."""
    v = order_section().get(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default


def signal_family(inst_upper: str) -> str:
    u = inst_upper.strip().upper()
    if u in ("NQ", "MNQ"):
        return "nq"
    if u in ("GC", "MGC"):
        return "gc"
    raise ValueError(
        f"Unsupported signal instrument {inst_upper!r} — use NQ/MNQ or GC/MGC (edit mapping if you add more)."
    )

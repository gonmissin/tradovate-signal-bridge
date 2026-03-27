"""
Flask webhook: POST JSON signal -> TV market entry + v1 SL / TP from app levels.

  pip install flask requests
  python app.py
"""

from __future__ import annotations

import threading
import time
from typing import Any

from flask import Flask, jsonify, request

from modules.auth import Auth
from modules.client_config import (
    connection_section,
    order_bool,
    order_section,
    signal_family,
    tv_bridge_placeholder_bid_ask,
)
from modules.console_theme import app_line
from modules.orders import Orders
from modules.trade_watch import TradeWatchManager

app = Flask(__name__)

trade_watch = TradeWatchManager(poll_seconds=5.0)
_watch_started = False
_watch_start_lock = threading.Lock()

_token_cache: dict[str, Any] = {"token": None, "base_url": None, "ts": 0.0}
_acct_cache: dict[str, Any] | None = None
_TOKEN_TTL = 80 * 60


def _coalesce(*vals):
    for v in vals:
        if v is not None and v != "":
            return v
    return None


def _auth():
    now = time.time()
    t, base = _token_cache["token"], _token_cache["base_url"]
    if t and base and (now - _token_cache["ts"]) < _TOKEN_TTL:
        return t, base
    conn = connection_section()
    user = str(conn.get("username") or "").strip()
    pwd = str(conn.get("password") or "").strip()
    if not user or not pwd:
        raise RuntimeError(
            "Missing login: set connection.username and connection.password in assets/config.json "
            "(run python main.py and complete setup)."
        )
    auth = Auth()
    token = auth._login(user, pwd, "")
    _token_cache["token"] = token
    _token_cache["base_url"] = auth.base_url
    _token_cache["ts"] = now
    return token, auth.base_url


def _instrument_block(fam: str) -> dict[str, str] | str | None:
    inst = order_section().get("instruments") or {}
    return inst.get(fam)


def _tv_instrument_for_signal(inst_key_upper: str) -> str:
    fam = signal_family(inst_key_upper)
    block = _instrument_block(fam)
    tv = ""
    if isinstance(block, dict):
        tv = str(block.get("tv") or "").strip()
    elif isinstance(block, str):
        tv = block.strip()
    if tv:
        return tv
    raise ValueError(
        f"Set order.instruments.{fam}.tv in assets/config.json for {inst_key_upper!r} signals."
    )


def _v1_symbol_for_signal(inst_key_upper: str) -> str | None:
    fam = signal_family(inst_key_upper)
    block = _instrument_block(fam)
    if isinstance(block, dict):
        v1 = str(block.get("v1") or "").strip()
        return v1 or None
    return None


def _tv_bridge_bid_ask_for_signal(inst_key_upper: str) -> tuple[float, float]:
    fam = signal_family(inst_key_upper)
    return tv_bridge_placeholder_bid_ask(fam)


def _account(orders: Orders, token: str, base_url: str) -> dict[str, Any]:
    global _acct_cache
    if _acct_cache is not None:
        return _acct_cache
    _acct_cache = orders.resolve_v1_trading_account_with_config(
        token, base_url, connection_section()
    )
    return _acct_cache


def signal_to_execution_params(data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Map incoming webhook body to Orders._execute kwargs.
    Returns None if the signal should be skipped (no trade).
    """
    if order_bool("skip_when_regime_suppressed", True) and data.get("regimeSuppressed"):
        return None

    action = _coalesce(data.get("action"), (data.get("raw") or {}).get("action"))
    if action != "ENTRY":
        return None

    direction = (data.get("direction") or "").strip().lower()
    if direction == "bullish":
        side = "buy"
    elif direction == "bearish":
        side = "sell"
    else:
        raise ValueError(f"Unknown direction: {data.get('direction')!r}")

    inst_key = (data.get("instrument") or "").strip().upper()
    if not inst_key:
        raise ValueError("Missing instrument")

    current_bid, current_ask = _tv_bridge_bid_ask_for_signal(inst_key)
    tv_inst = _tv_instrument_for_signal(inst_key)
    v1_sym = _v1_symbol_for_signal(inst_key)

    app_levels = data.get("appLevels") if isinstance(data.get("appLevels"), dict) else {}

    stop = _coalesce(
        data.get("app_stop"),
        data.get("stop"),
        app_levels.get("sl_recommended"),
        app_levels.get("sl_tight"),
    )
    tp1 = _coalesce(
        data.get("app_tp1"),
        data.get("tp1"),
        app_levels.get("tp1"),
    )
    tp2 = _coalesce(
        data.get("app_target"),
        data.get("target"),
        app_levels.get("tp2"),
    )
    if stop is not None:
        stop = float(stop)
    if tp1 is not None:
        tp1 = float(tp1)
    if tp2 is not None:
        tp2 = float(tp2)

    ord_c = order_section()
    order_qty = int(ord_c.get("order_qty", 1))
    take_profit_2 = None
    tp1_qty = None
    tp2_qty = None

    if order_bool("place_two_tps", False) and tp1 is not None and tp2 is not None:
        take_profit_2 = tp2
        tp1_qty = int(ord_c.get("tp1_qty", 1))
        tp2_qty = int(ord_c.get("tp2_qty", 0))
        if tp1_qty + tp2_qty != order_qty:
            raise ValueError(
                f"tp1_qty + tp2_qty must equal order_qty ({order_qty}); "
                f"got {tp1_qty}+{tp2_qty} (set in assets/config.json)"
            )

    conn_c = connection_section()
    tv_acct = str(conn_c.get("tv_account") or "").strip()
    if not tv_acct:
        raise ValueError("Set connection.tv_account in assets/config.json (TV bridge account id, e.g. D45219551).")

    entry_price = float(current_ask) if side == "buy" else float(current_bid)

    return {
        "tv_account": tv_acct,
        "side": side,
        "instrument": tv_inst,
        "order_qty": order_qty,
        "current_bid": current_bid,
        "current_ask": current_ask,
        "entry_price": entry_price,
        "stop_loss": stop,
        "take_profit_1": tp1,
        "take_profit_2": take_profit_2,
        "tp1_qty": tp1_qty,
        "tp2_qty": tp2_qty,
        "v1_symbol": v1_sym if v1_sym else None,
        "fill_wait_seconds": float(ord_c.get("fill_wait_seconds", 1.5)),
    }


def _ensure_trade_watch():
    global _watch_started
    with _watch_start_lock:
        if _watch_started:
            return
        trade_watch.configure_auth(_auth)
        trade_watch.start_background()
        _watch_started = True


@app.before_request
def _start_watch_on_first_request():
    _ensure_trade_watch()


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/webhook")
def webhook():
    if not request.is_json:
        return jsonify({"ok": False, "error": "Expected application/json"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Body must be a JSON object"}), 400

    try:
        params = signal_to_execution_params(data)
        if params is None:
            return jsonify({"ok": True, "skipped": True, "reason": "filtered"}), 200

        token, base_url = _auth()
        orders = Orders()
        needs_v1 = (
            params.get("stop_loss") is not None
            or params.get("take_profit_1") is not None
            or params.get("take_profit_2") is not None
        )
        acct = _account(orders, token, base_url) if needs_v1 else None

        result = orders._execute(
            token,
            base_url,
            account_id=acct["id"] if acct else None,
            account_spec=acct["name"] if acct else None,
            **{k: v for k, v in params.items() if k != "entry_price"},
        )
        sym = params.get("v1_symbol") or params["instrument"]
        try:
            trade_watch.register_brackets(
                account_id=int(acct["id"]) if acct else None,
                account_spec=str(acct["name"]) if acct else None,
                v1_symbol=str(sym),
                entry_side=str(params["side"]),
                entry_price=float(params["entry_price"]),
                order_qty=int(params["order_qty"]),
                take_profit_2=params.get("take_profit_2"),
                tp1_qty_param=params.get("tp1_qty"),
                tp2_qty_param=params.get("tp2_qty"),
                take_profit_1_price=params.get("take_profit_1"),
                execute_result=result,
            )
        except Exception as e:
            app_line("warn", f"watch register skipped: {e}")
        return jsonify({"ok": True, "result": result}), 200
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)

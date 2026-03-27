#!/usr/bin/env python3
"""
Bestard Productions — Tradovate terminal client (no tkinter).
First start: prompts for login, size, TP splits, then writes assets/config.json.
"""

from __future__ import annotations

import getpass
import json
import os
import shutil
import sys
import time
from pathlib import Path

from modules.auth import Auth
from modules.client_config import developer_mode as config_developer_mode
from modules.client_config import tv_bridge_placeholder_bid_ask
from modules.console_theme import accent, bold, dim, err, info, ok, print_execute_result_bundle, warn
from modules.orders import Orders

CONFIG_PATH = Path(__file__).resolve().parent / "assets" / "config.json"

BANNER = r"""
  ╭──────────────────────────────────────────────────────────────╮
  │                                                              │
  │                   Bestard Productions                        │
  │                    tradovate  ·  client                      │
  │                                                              │
  ╰──────────────────────────────────────────────────────────────╯
"""


def term_width() -> int:
    try:
        return max(40, shutil.get_terminal_size(fallback=(88, 24)).columns)
    except OSError:
        return 88


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="", flush=True)
    elif os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def center_line(line: str) -> str:
    w = term_width()
    s = line.rstrip("\r\n")
    n = len(s)
    if n >= w:
        return s[:w]
    return " " * ((w - n) // 2) + s


def center_block(text: str) -> None:
    for ln in text.strip("\n").split("\n"):
        print(center_line(ln))


def center_styled(plain: str, sty) -> None:
    w = term_width()
    n = len(plain)
    if n >= w:
        print(sty(plain[:w]))
        return
    print(" " * ((w - n) // 2) + sty(plain))


def content_pad() -> int:
    """Left pad so forms ~64 cols sit near center."""
    return max(0, (term_width() - 64) // 2)


def input_centered_prompt(prompt_plain: str) -> str:
    pad = max(0, (term_width() - len(prompt_plain) - 24) // 2)
    return input(" " * pad + accent(prompt_plain)).strip()


def log(kind: str, msg: str) -> None:
    sty = {"trade": warn, "ok": ok, "err": err, "info": info, "dim": dim}.get(kind, info)
    for part in msg.splitlines():
        if not part.strip():
            print()
            continue
        center_styled(part, sty)


def default_config() -> dict:
    return {
        "connection": {
            "tv_account": "D45219551",
            "username": "",
            "password": "",
            "v1_account_id": None,
            "v1_account_spec": "",
        },
        "order": {
            "quote_family": "gc",
            "side": "buy",
            "order_qty": 1,
            "tp1_qty": 1,
            "tp2_qty": 0,
            "fill_wait_seconds": 1.5,
            "instruments": {
                "nq": {"tv": "NQM6", "v1": ""},
                "gc": {"tv": "MGCJ6", "v1": ""},
            },
            "place_two_tps": False,
            "skip_when_regime_suppressed": True,
            "test_auto_flatten_seconds": 5.0,
        },
    }


def save_config_file(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = data.get("connection") or {}
    data = {**data, "connection": {k: v for k, v in c.items() if k != "device_id"}}
    o = data.get("order")
    if isinstance(o, dict):
        data = {**data, "order": {k: v for k, v in o.items() if k != "quotes"}}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_config_file() -> dict:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        data = default_config()
        save_config_file(data)
        return data
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    raw.setdefault("developer_mode", False)
    conn = raw.setdefault("connection", {})
    for k in ("username", "password", "tv_account", "v1_account_spec"):
        conn.setdefault(k, default_config()["connection"].get(k, ""))
    conn.setdefault("v1_account_id", default_config()["connection"].get("v1_account_id"))
    if "device_id" in conn:
        del conn["device_id"]
    ord_ = raw.setdefault("order", {})
    ord_.pop("quotes", None)
    ord_.setdefault("quote_family", "gc")
    ord_.setdefault("fill_wait_seconds", 1.5)
    ord_.setdefault("order_qty", 1)
    ord_.setdefault("tp1_qty", 1)
    ord_.setdefault("tp2_qty", 0)
    ord_.setdefault("place_two_tps", False)
    ord_.setdefault("skip_when_regime_suppressed", True)
    ord_.setdefault("test_auto_flatten_seconds", 5.0)
    if "instruments" not in ord_:
        legacy_tv = str(ord_.get("instrument_tv", "") or "").strip()
        legacy_v1 = str(ord_.get("v1_symbol", "") or "").strip()
        qf = str(ord_.get("quote_family") or "gc").lower()
        ord_["instruments"] = {
            "nq": {"tv": "NQM6", "v1": ""},
            "gc": {"tv": "MGCJ6", "v1": ""},
        }
        if legacy_tv or legacy_v1:
            if qf == "nq":
                if legacy_tv:
                    ord_["instruments"]["nq"]["tv"] = legacy_tv
                ord_["instruments"]["nq"]["v1"] = legacy_v1
            else:
                if legacy_tv:
                    ord_["instruments"]["gc"]["tv"] = legacy_tv
                ord_["instruments"]["gc"]["v1"] = legacy_v1
        ord_.pop("instrument_tv", None)
        ord_.pop("v1_symbol", None)
    else:
        for fam in ("nq", "gc"):
            blk = ord_["instruments"].setdefault(fam, {})
            if isinstance(blk, str):
                ord_["instruments"][fam] = {"tv": blk, "v1": ""}
            else:
                blk.setdefault("tv", "NQM6" if fam == "nq" else "MGCJ6")
                blk.setdefault("v1", "")
    return raw


def needs_first_setup(data: dict) -> bool:
    c = data.get("connection") or {}
    return not str(c.get("username") or "").strip()


def _ask(prompt: str, default: str = "") -> str:
    d = f" [{default}]" if default else ""
    p = content_pad()
    s = input(" " * p + accent(prompt) + d + ": ").strip()
    return s if s else default


def _ask_int(prompt: str, default: int) -> int:
    while True:
        s = _ask(prompt, str(default))
        try:
            v = int(s)
            if v < 0:
                raise ValueError
            return v
        except ValueError:
            log("err", "Enter a non-negative integer.")


def _ask_float(prompt: str, default: float) -> float:
    while True:
        s = _ask(prompt, str(default))
        try:
            return float(s)
        except ValueError:
            log("err", "Enter a number.")


def _ask_yn(prompt: str, default: bool) -> bool:
    suf = " [Y/n]" if default else " [y/N]"
    s = _ask(prompt + suf, "y" if default else "n").strip().lower()
    if not s:
        return default
    return s in ("y", "yes", "1")


def run_first_setup(base: dict | None = None) -> dict:
    d = json.loads(json.dumps(base or load_config_file()))
    clear_screen()
    center_block(BANNER)
    print()
    center_styled("First-time setup", bold)
    center_styled("Answers save to assets/config.json", dim)
    print()

    c = d.setdefault("connection", {})
    o = d.setdefault("order", {})

    c["username"] = _ask("Tradovate username", c.get("username") or "")
    pw = getpass.getpass(" " * content_pad() + "Password: ").strip()
    if not pw:
        pw = str(c.get("password") or "").strip()
    while not pw:
        log("err", "Password cannot be empty.")
        pw = getpass.getpass(" " * content_pad() + "Password: ").strip()
    c["password"] = pw
    c["tv_account"] = _ask("TV account id (URL segment, e.g. D45219551)", c.get("tv_account") or "D45219551")

    o["order_qty"] = _ask_int("Fill quantity (contracts per entry)", int(o.get("order_qty") or 1))
    o["tp1_qty"] = _ask_int("Contracts to take off at TP1", int(o.get("tp1_qty") or 1))
    o["tp2_qty"] = _ask_int("Contracts at TP2 (0 = only one TP)", int(o.get("tp2_qty") or 0))

    if o["tp2_qty"] > 0 and o["tp1_qty"] + o["tp2_qty"] != o["order_qty"]:
        log("warn", f"tp1 ({o['tp1_qty']}) + tp2 ({o['tp2_qty']}) should usually equal order_qty ({o['order_qty']}).")

    o["quote_family"] = (_ask("Default test family: nq or gc", o.get("quote_family") or "gc") or "gc").lower()
    if o["quote_family"] not in ("nq", "gc"):
        o["quote_family"] = "gc"

    side = (_ask("Default side for manual test (buy/sell)", o.get("side") or "buy") or "buy").lower()
    o["side"] = side if side in ("buy", "sell") else "buy"

    ins = o.setdefault("instruments", {})
    nq = ins.setdefault("nq", {"tv": "NQM6", "v1": ""})
    gc = ins.setdefault("gc", {"tv": "MGCJ6", "v1": ""})
    nq["tv"] = _ask("NQ / MNQ — TV instrument symbol", nq.get("tv") or "NQM6")
    nq["v1"] = _ask("NQ — v1 symbol (blank ok)", nq.get("v1") or "")
    gc["tv"] = _ask("GC / MGC — TV instrument symbol", gc.get("tv") or "MGCJ6")
    gc["v1"] = _ask("GC — v1 symbol (blank ok)", gc.get("v1") or "")

    o["fill_wait_seconds"] = _ask_float("Bracket delay after fill (seconds)", float(o.get("fill_wait_seconds") or 1.5))

    o["place_two_tps"] = _ask_yn(
        "Webhook: use two take-profits when signal has TP1 + target (runner / BE logic)",
        bool(o.get("place_two_tps", False)),
    )
    o["skip_when_regime_suppressed"] = _ask_yn(
        "Skip ENTRY when JSON has regimeSuppressed",
        bool(o.get("skip_when_regime_suppressed", True)),
    )

    save_config_file(d)
    log("ok", f"Saved {CONFIG_PATH}")
    return d


def print_config_summary(d: dict) -> None:
    c, o = d.get("connection") or {}, d.get("order") or {}
    print()
    center_styled("── config summary ──", accent)
    lines = [
        f"developer_mode: {ok('on') if config_developer_mode() else dim('off')}",
        f"username     : {c.get('username')}",
        f"tv_account   : {c.get('tv_account')}",
        f"order_qty    : {o.get('order_qty')}",
        f"tp1_qty      : {o.get('tp1_qty')}   tp2_qty: {o.get('tp2_qty')}",
        f"quote_family : {o.get('quote_family')}   side: {o.get('side')}",
        f"two TPs      : {o.get('place_two_tps')}   skip regimeSuppressed: {o.get('skip_when_regime_suppressed')}",
    ]
    ins = o.get("instruments") or {}
    lines.append(f"NQ tv        : {(ins.get('nq') or {}).get('tv')}")
    lines.append(f"GC tv        : {(ins.get('gc') or {}).get('tv')}")
    for line in lines:
        n = len(line)
        pad = max(0, (term_width() - n) // 2)
        print(" " * pad + dim(line))
    print()


def execute_market(d: dict) -> None:
    conn = d["connection"]
    o = d["order"]
    if not conn.get("username") or not conn.get("password"):
        log("err", "Missing username/password. Run setup (option 3).")
        return

    order_qty = int(o.get("order_qty") or 1)
    fam = str(o.get("quote_family") or "gc").lower()
    bid, ask = tv_bridge_placeholder_bid_ask(fam)

    inst_block = (o.get("instruments") or {}).get(fam) or {}
    tv_sym = str(inst_block.get("tv") or "").strip() if isinstance(inst_block, dict) else ""
    if not tv_sym:
        log("err", f"Set instruments.{fam}.tv")
        return
    v1 = str(inst_block.get("v1") or "").strip() or None

    log("trade", f"{o.get('side','buy').upper()}  {order_qty}× {tv_sym}  bid {bid}  ask {ask}")

    try:
        log("info", "Logging in…")
        auth = Auth()
        token = auth._login(conn["username"], conn["password"], "")
        log("ok", "Token OK.")

        orders = Orders()
        # Market-only test uses TV bridge URL only; v1 accountId is only for /order/placeorder (SL/TP).
        entry_side = str(o.get("side") or "buy")
        result = orders._execute(
            token,
            auth.base_url,
            tv_account=conn["tv_account"],
            side=entry_side,
            instrument=tv_sym,
            order_qty=order_qty,
            current_bid=float(bid),
            current_ask=float(ask),
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            tp1_qty=None,
            tp2_qty=None,
            account_id=None,
            account_spec=None,
            v1_symbol=v1,
            fill_wait_seconds=float(o.get("fill_wait_seconds") or 1.5),
        )
        flat_s = float(o.get("test_auto_flatten_seconds") or 0)
        if flat_s > 0:
            log(
                "info",
                f"Test flatten: opposite TV market in {flat_s:.0f}s (set order.test_auto_flatten_seconds to 0 to skip)…",
            )
            time.sleep(flat_s)
            result["flatten"] = orders.tv_market_flatten(
                token,
                conn["tv_account"],
                entry_side=entry_side,
                instrument=tv_sym,
                order_qty=order_qty,
                current_bid=float(bid),
                current_ask=float(ask),
            )
        print_execute_result_bundle(result)
        log("ok", "Finished.")
    except Exception as e:
        log("err", str(e))


def menu() -> None:
    if sys.platform == "win32":
        try:
            os.system("")
        except OSError:
            pass

    data = load_config_file()
    if needs_first_setup(data):
        data = run_first_setup(data)
        clear_screen()

    while True:
        clear_screen()
        center_block(BANNER)
        print()
        center_styled("Main menu", bold)
        center_styled("1)  Market test (from config)", dim)
        center_styled("2)  Show config summary", dim)
        center_styled("3)  Run setup again (overwrite fields)", dim)
        center_styled("4)  Quit", dim)
        print()
        choice = input_centered_prompt("Choose [1-4]: ")

        if choice == "1":
            clear_screen()
            center_styled("Market test", bold)
            print()
            data = load_config_file()
            execute_market(data)
        elif choice == "2":
            clear_screen()
            data = load_config_file()
            print_config_summary(data)
        elif choice == "3":
            data = load_config_file()
            run_first_setup(data)
            clear_screen()
        elif choice == "4":
            clear_screen()
            center_styled("Bye.", info)
            break
        else:
            center_styled("Pick 1–4.", err)

        print()
        input_centered_prompt("Press Enter to continue…")


if __name__ == "__main__":
    try:
        menu()
    except KeyboardInterrupt:
        print()
        log("dim", "Interrupted.")

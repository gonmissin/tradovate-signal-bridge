"""
Background poll (default 5s) for v1 bracket orders after a webhook entry.

- TP1 filled  -> cancel working stop; if runner (tp2_qty > 0) place stop at entry (BE).
- Stop filled before BE -> cancel all working TP limits (TP1 + TP2).
- Stop filled after BE   -> cancel TP2 only.
- TP2 filled             -> cancel working stop (flat at target).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from modules.console_theme import watch_line
from modules.orders import Orders


def _filled(st: Any) -> bool:
    return str(st or "") in ("Filled", "Completed")


@dataclass
class _Watch:
    wid: str
    account_id: int
    account_spec: str
    v1_symbol: str
    entry_side: str
    entry_price: float
    order_qty: int
    tp1_qty: int
    tp2_qty: int
    stop_order_id: int | None
    tp1_order_id: int | None
    tp2_order_id: int | None
    be_moved: bool = False


class TradeWatchManager:
    def __init__(self, poll_seconds: float = 5.0):
        self.poll_seconds = max(5.0, float(poll_seconds))
        self._lock = threading.Lock()
        self._watches: list[_Watch] = []
        self._orders = Orders()
        self._auth_fn: Callable[[], tuple[str, str]] | None = None
        self._thread_started = False

    def configure_auth(self, auth_fn: Callable[[], tuple[str, str]]) -> None:
        self._auth_fn = auth_fn

    def start_background(self) -> None:
        if self._thread_started:
            return
        self._thread_started = True
        t = threading.Thread(target=self._loop, name="trade-watch", daemon=True)
        t.start()

    def register_brackets(
        self,
        *,
        account_id: int | None,
        account_spec: str | None,
        v1_symbol: str,
        entry_side: str,
        entry_price: float,
        order_qty: int,
        take_profit_2: float | None,
        tp1_qty_param: int | None,
        tp2_qty_param: int | None,
        take_profit_1_price: float | None,
        execute_result: dict[str, Any],
    ) -> None:
        stop_id = Orders.place_response_order_id(execute_result.get("stop_loss"))
        tp1_id = Orders.place_response_order_id(execute_result.get("take_profit_1"))
        tp2_id = Orders.place_response_order_id(execute_result.get("take_profit_2"))

        if stop_id is None and tp1_id is None and tp2_id is None:
            return

        if account_id is None or not (account_spec or "").strip():
            watch_line("warn", "register skipped — v1 account required for bracket ids")
            return

        if take_profit_2 is not None:
            tp1_q = int(tp1_qty_param or 0)
            tp2_q = int(tp2_qty_param or 0)
        else:
            tp1_q = int(order_qty) if take_profit_1_price is not None else 0
            tp2_q = 0

        w = _Watch(
            wid=uuid.uuid4().hex[:12],
            account_id=int(account_id),
            account_spec=str(account_spec),
            v1_symbol=str(v1_symbol),
            entry_side=str(entry_side).strip().lower(),
            entry_price=float(entry_price),
            order_qty=int(order_qty),
            tp1_qty=tp1_q,
            tp2_qty=tp2_q,
            stop_order_id=stop_id,
            tp1_order_id=tp1_id,
            tp2_order_id=tp2_id,
        )
        with self._lock:
            self._watches.append(w)
        watch_line(
            "ok",
            f"registered {w.wid}  ·  sl={stop_id}  ·  tp1={tp1_id}  ·  tp2={tp2_id}",
        )

    def _loop(self) -> None:
        while True:
            time.sleep(self.poll_seconds)
            try:
                if self._auth_fn is None:
                    continue
                token, base_url = self._auth_fn()
                self.tick(token, base_url)
            except Exception as e:
                watch_line("err", f"loop error: {e}")

    def _status_map(self, token: str, base_url: str) -> dict[int, str]:
        raw = self._orders._v1_order_list(token, base_url)
        out: dict[int, str] = {}
        for o in raw:
            if not isinstance(o, dict):
                continue
            oid = o.get("id")
            if oid is None:
                oid = o.get("orderId")
            if oid is None:
                continue
            st = o.get("ordStatus") or o.get("status") or ""
            out[int(oid)] = str(st)
        return out

    def _safe_cancel(self, token: str, base_url: str, oid: int | None) -> None:
        if oid is None:
            return
        try:
            self._orders._v1_cancel_order(token, base_url, int(oid))
        except Exception as e:
            print(f"[watch] cancel {oid}: {e}")

    def tick(self, token: str, base_url: str) -> None:
        with self._lock:
            watches = list(self._watches)
        if not watches:
            return

        status = self._status_map(token, base_url)
        done_ids: list[str] = []

        for w in watches:
            st_sl = status.get(w.stop_order_id) if w.stop_order_id is not None else None
            st_t1 = status.get(w.tp1_order_id) if w.tp1_order_id is not None else None
            st_t2 = status.get(w.tp2_order_id) if w.tp2_order_id is not None else None

            if w.tp2_order_id is not None and _filled(st_t2):
                watch_line("info", f"{w.wid} TP2 filled → cancel stop")
                self._safe_cancel(token, base_url, w.stop_order_id)
                done_ids.append(w.wid)
                continue

            if w.stop_order_id is not None and _filled(st_sl):
                if w.be_moved:
                    watch_line("info", f"{w.wid} BE stop filled → cancel TP2")
                    self._safe_cancel(token, base_url, w.tp2_order_id)
                else:
                    watch_line("info", f"{w.wid} stop loss filled → cancel TP levels")
                    self._safe_cancel(token, base_url, w.tp1_order_id)
                    self._safe_cancel(token, base_url, w.tp2_order_id)
                done_ids.append(w.wid)
                continue

            if (
                w.tp1_order_id is not None
                and _filled(st_t1)
                and not w.be_moved
            ):
                watch_line("ok", f"{w.wid} TP1 filled → move stop to BE")
                self._safe_cancel(token, base_url, w.stop_order_id)
                new_stop_id: int | None = None
                if w.tp2_qty > 0:
                    ex = self._orders._exit_action(w.entry_side)
                    try:
                        resp = self._orders._v1_place_order(
                            token,
                            base_url,
                            account_id=w.account_id,
                            account_spec=w.account_spec,
                            symbol=w.v1_symbol,
                            action=ex,
                            order_qty=int(w.tp2_qty),
                            order_type="Stop",
                            stop_price=float(w.entry_price),
                        )
                        new_stop_id = Orders.place_response_order_id(resp)
                    except Exception as e:
                        watch_line("err", f"{w.wid} BE stop place failed: {e}")
                else:
                    done_ids.append(w.wid)
                with self._lock:
                    for x in self._watches:
                        if x.wid == w.wid:
                            x.be_moved = True
                            x.stop_order_id = new_stop_id
                            break
                continue

        if done_ids:
            with self._lock:
                self._watches = [x for x in self._watches if x.wid not in done_ids]

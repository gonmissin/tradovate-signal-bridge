import time
import uuid
from typing import Any

import requests

from modules.console_theme import print_http_trace

TV_DEMO_BASE = 'https://tv-demo.tradovateapi.com'
# Same value as Auth._login → accessToken: use it as Bearer for both tv-demo and v1.


class Orders:
    def __init__(self):
        self.client = requests.Session()

    def _headers_json(self, token: str):
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _headers_tv_form(self, token: str):
        """TV bridge headers; ``token`` is the same accessToken from login (Bearer)."""
        return {
            'accept': 'application/json',
            'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'authorization': f'Bearer {token}',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.tradingview.com',
            'referer': 'https://www.tradingview.com/',
            'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'cross-site',
            'user-agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36'
            ),
        }

    @staticmethod
    def _v1_normalize_list_payload(data: Any) -> list[dict[str, Any]]:
        """Unwrap Tradovate list responses: raw list, or ``{ "d": [...] }``, etc."""
        if data is None:
            return []
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if not isinstance(data, dict):
            return []
        d = data.get('d')
        if isinstance(d, list):
            return [x for x in d if isinstance(x, dict)]
        if isinstance(d, dict):
            return [d]
        for key in ('items', 'accounts', 'data', 'results'):
            v = data.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return []

    @staticmethod
    def _v1_normalize_object_payload(data: Any) -> dict[str, Any] | None:
        """Unwrap single-entity responses: ``{ "d": { ... } }`` or flat object."""
        if not isinstance(data, dict):
            return None
        inner = data.get('d')
        if isinstance(inner, dict):
            return inner
        if 'name' in data or 'id' in data or 'accountId' in data:
            return data
        return None

    @staticmethod
    def _coerce_account_dict(raw: dict[str, Any]) -> dict[str, Any] | None:
        """Normalize id + name (accountSpec) for v1 placeorder."""
        aid = raw.get('id')
        if aid is None:
            aid = raw.get('accountId')
        if aid is None:
            return None
        try:
            iid = int(aid)
        except (TypeError, ValueError):
            return None
        name = raw.get('name') or raw.get('accountSpec') or raw.get('accountName')
        if name is None or not str(name).strip():
            return None
        out = dict(raw)
        out['id'] = iid
        out['name'] = str(name).strip()
        return out

    @staticmethod
    def _account_passes_filters(c: dict[str, Any], *, strict_active: bool) -> bool:
        if c.get('archived') is True:
            return False
        if strict_active and c.get('active') is False:
            return False
        return True

    def _pick_account_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        coerced: list[dict[str, Any]] = []
        for row in rows:
            x = self._coerce_account_dict(row)
            if x:
                coerced.append(x)
        for strict in (True, False):
            for c in coerced:
                if self._account_passes_filters(c, strict_active=strict):
                    return c
        return None

    def _get_orders(self, token: str, base_url: str) -> list[dict[str, Any]]:
        """GET /account/list on v1 API (demo or live host)."""
        base = base_url.rstrip('/')
        r = self.client.get(
            f'{base}/account/list',
            headers=self._headers_json(token),
            timeout=30,
        )
        r.raise_for_status()
        return self._v1_normalize_list_payload(r.json())

    def _get_trading_permission_list(self, token: str, base_url: str) -> list[dict[str, Any]]:
        base = base_url.rstrip('/')
        r = self.client.get(
            f'{base}/tradingPermission/list',
            headers=self._headers_json(token),
            timeout=30,
        )
        r.raise_for_status()
        return self._v1_normalize_list_payload(r.json())

    def _get_account_item(self, token: str, base_url: str, account_id: int) -> dict[str, Any] | None:
        base = base_url.rstrip('/')
        r = self.client.get(
            f'{base}/account/item',
            params={'id': int(account_id)},
            headers=self._headers_json(token),
            timeout=30,
        )
        r.raise_for_status()
        return self._v1_normalize_object_payload(r.json())

    def _get_account_find(self, token: str, base_url: str, name: str) -> dict[str, Any] | None:
        """GET /account/find?name= — Tradovate account *name* often matches TV bridge id (e.g. D45219551)."""
        n = str(name or "").strip()
        if not n:
            return None
        base = base_url.rstrip('/')
        try:
            r = self.client.get(
                f'{base}/account/find',
                params={'name': n},
                headers=self._headers_json(token),
                timeout=30,
            )
        except requests.RequestException:
            return None
        if r.status_code != 200:
            return None
        obj = self._v1_normalize_object_payload(r.json())
        if not obj:
            return None
        if obj.get('errorText'):
            return None
        return obj

    def _get_position_list(self, token: str, base_url: str) -> list[dict[str, Any]]:
        base = base_url.rstrip('/')
        r = self.client.get(
            f'{base}/position/list',
            headers=self._headers_json(token),
            timeout=30,
        )
        r.raise_for_status()
        return self._v1_normalize_list_payload(r.json())

    def _first_usable_from_account_ids(
        self,
        token: str,
        base_url: str,
        account_ids: list[int],
    ) -> dict[str, Any] | None:
        seen: set[int] = set()
        for aid in account_ids:
            if aid in seen:
                continue
            seen.add(aid)
            item = self._get_account_item(token, base_url, aid)
            if not item:
                continue
            c = self._coerce_account_dict(item)
            if c and self._account_passes_filters(c, strict_active=False):
                return c
        return None

    def resolve_v1_trading_account(
        self,
        token: str,
        base_url: str,
        *,
        name_hints: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """
        Resolve accountId + accountSpec for placeorder.

        Order: /account/find for each unique name hint (tv_account is usually the account *name*),
        then /account/list, /tradingPermission/list + /account/item, /position/list, /order/list.
        """
        ordered_names: list[str] = []
        for nm in name_hints or []:
            s = str(nm).strip()
            if s and s not in ordered_names:
                ordered_names.append(s)
        for nm in ordered_names:
            item = self._get_account_find(token, base_url, nm)
            if item:
                c = self._coerce_account_dict(item)
                if c and self._account_passes_filters(c, strict_active=False):
                    return c

        rows = self._get_orders(token, base_url)
        acct = self._pick_account_from_rows(rows)
        if acct:
            return acct

        skip_status = {'revoked', 'declined'}
        seen: set[int] = set()
        for p in self._get_trading_permission_list(token, base_url):
            st = str(p.get('status') or '').strip().lower()
            if st in skip_status:
                continue
            aid = p.get('accountId')
            if aid is None:
                continue
            try:
                iid = int(aid)
            except (TypeError, ValueError):
                continue
            if iid in seen:
                continue
            seen.add(iid)
            item = self._get_account_item(token, base_url, iid)
            if not item:
                continue
            c = self._coerce_account_dict(item)
            if c and self._account_passes_filters(c, strict_active=False):
                return c

        pos_ids: list[int] = []
        for p in self._get_position_list(token, base_url):
            aid = p.get('accountId')
            if aid is None:
                continue
            try:
                pos_ids.append(int(aid))
            except (TypeError, ValueError):
                continue
        found = self._first_usable_from_account_ids(token, base_url, pos_ids)
        if found:
            return found

        ord_ids: list[int] = []
        for o in self._v1_order_list(token, base_url):
            aid = o.get('accountId')
            if aid is None:
                continue
            try:
                ord_ids.append(int(aid))
            except (TypeError, ValueError):
                continue
        return self._first_usable_from_account_ids(token, base_url, ord_ids)

    def resolve_v1_trading_account_with_config(
        self,
        token: str,
        base_url: str,
        conn: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply optional connection.v1_account_id / v1_account_spec, else auto-resolve."""
        raw_id = conn.get('v1_account_id')
        raw_spec = str(conn.get('v1_account_spec') or '').strip()
        if raw_id is not None and str(raw_id).strip() != '':
            try:
                aid = int(raw_id)
            except (TypeError, ValueError) as e:
                raise RuntimeError(f'Invalid connection.v1_account_id: {raw_id!r}') from e
            if raw_spec:
                return {'id': aid, 'name': raw_spec}
            item = self._get_account_item(token, base_url, aid)
            if not item:
                raise RuntimeError(
                    f'/account/item?id={aid} returned empty; set connection.v1_account_spec in assets/config.json.'
                )
            c = self._coerce_account_dict(item)
            if not c:
                raise RuntimeError(
                    f'/account/item?id={aid} had no usable name; set connection.v1_account_spec in config.json.'
                )
            return c

        tv = str(conn.get('tv_account') or '').strip()
        name_hints: list[str] = []
        if tv:
            name_hints.append(tv)
        if raw_spec and raw_spec not in name_hints:
            name_hints.append(raw_spec)

        acct = self.resolve_v1_trading_account(token, base_url, name_hints=name_hints or None)
        if acct:
            return acct

        rows = self._get_orders(token, base_url)
        preview = repr(rows)[:1800] if rows else repr(rows)
        raise RuntimeError(
            'No usable v1 trading account. Tried /account/find?name= (connection.tv_account), '
            '/account/list, /tradingPermission/list, /position/list, /order/list. '
            'Set connection.v1_account_id + v1_account_spec if needed. '
            f'Parsed /account/list rows (truncated): {preview}'
        )

    def _v1_order_list(self, token: str, base_url: str) -> list:
        base = base_url.rstrip('/')
        r = self.client.get(
            f'{base}/order/list',
            headers=self._headers_json(token),
            timeout=30,
        )
        r.raise_for_status()
        return self._v1_normalize_list_payload(r.json())

    def _v1_cancel_order(self, token: str, base_url: str, order_id: int) -> dict:
        base = base_url.rstrip('/')
        body = {'orderId': int(order_id), 'isAutomated': True}
        r = self.client.post(
            f'{base}/order/cancelorder',
            json=body,
            headers=self._headers_json(token),
            timeout=30,
        )
        print_http_trace(f"v1 cancel order {order_id}", r.status_code, r.text or "")
        r.raise_for_status()
        return r.json() if r.text else {}

    @staticmethod
    def place_response_order_id(resp) -> int | None:
        """Best-effort order id from /order/placeorder JSON."""
        if not isinstance(resp, dict):
            return None
        d = resp.get('d')
        if isinstance(d, dict) and d.get('orderId') is not None:
            return int(d['orderId'])
        if isinstance(d, int):
            return int(d)
        if resp.get('orderId') is not None:
            return int(resp['orderId'])
        return None

    @staticmethod
    def _normalize_side_tv(side: str) -> str:
        s = side.strip().lower()
        if s not in ('buy', 'sell'):
            raise ValueError("side must be 'buy' or 'sell' (TV form)")
        return s

    @staticmethod
    def _normalize_side_v1(side: str) -> str:
        s = side.strip().lower()
        if s == 'buy':
            return 'Buy'
        if s == 'sell':
            return 'Sell'
        if side in ('Buy', 'Sell'):
            return side
        raise ValueError("side must be Buy/Sell or buy/sell")

    @staticmethod
    def _exit_action(entry_side: str) -> str:
        s = entry_side.strip().lower()
        if s == 'buy':
            return 'Sell'
        if s == 'sell':
            return 'Buy'
        raise ValueError('entry side must be buy or sell')

    def _tv_market_order(
        self,
        token: str,
        tv_account: str,
        *,
        instrument: str,
        qty: int,
        side: str,
        current_bid: float,
        current_ask: float,
        duration_type: str = 'Day',
        locale: str = 'en',
        request_id: str | None = None,
        trace_label: str = 'TV market',
    ):
        """
        POST /accounts/{tv_account}/orders — TradingView bridge market order.

        ``current_bid`` / ``current_ask`` are required form fields. Callers pass
        values from ``TV_BRIDGE_BID_ASK`` in ``client_config.py`` (static
        placeholders). They do not need to match the live tape for demo bridge
        routing.
        """
        side_tv = self._normalize_side_tv(side)
        url = f'{TV_DEMO_BASE.rstrip("/")}/accounts/{tv_account}/orders'
        params = {
            'locale': locale,
            'requestId': request_id or uuid.uuid4().hex[:12],
        }
        data = {
            'currentAsk': str(current_ask),
            'currentBid': str(current_bid),
            'durationType': duration_type,
            'instrument': instrument,
            'qty': str(int(qty)),
            'side': side_tv,
            'type': 'market',
        }
        r = self.client.post(
            url,
            params=params,
            headers=self._headers_tv_form(token),
            data=data,
            timeout=30,
        )
        print_http_trace(trace_label, r.status_code, r.text or "")
        r.raise_for_status()
        return r.json() if r.text else {}

    def tv_market_flatten(
        self,
        token: str,
        tv_account: str,
        *,
        entry_side: str,
        instrument: str,
        order_qty: int,
        current_bid: float,
        current_ask: float,
        duration_type: str = 'Day',
        locale: str = 'en',
        request_id: str | None = None,
    ):
        """
        Flatten via **opposite-side** TV bridge market order (same qty as the test entry).
        Example: entry was 1 contract **buy** → this sends 1 contract **sell**.
        Same static bid/ask as entry is fine. No separate “close position” REST URL.
        """
        exit_side = self._exit_action(entry_side).lower()
        return self._tv_market_order(
            token,
            tv_account,
            instrument=instrument,
            qty=order_qty,
            side=exit_side,
            current_bid=current_bid,
            current_ask=current_ask,
            duration_type=duration_type,
            locale=locale,
            request_id=request_id,
            trace_label='TV market (flatten)',
        )

    def _v1_place_order(
        self,
        token: str,
        base_url: str,
        *,
        account_id: int,
        account_spec: str,
        symbol: str,
        action: str,
        order_qty: int,
        order_type: str,
        time_in_force: str = 'Day',
        price: float | None = None,
        stop_price: float | None = None,
    ):
        """POST /order/placeorder on v1 host."""
        base = base_url.rstrip('/')
        body: dict = {
            'accountSpec': account_spec,
            'accountId': int(account_id),
            'action': self._normalize_side_v1(action),
            'symbol': symbol,
            'orderQty': int(order_qty),
            'orderType': order_type,
            'timeInForce': time_in_force,
            'isAutomated': True,
        }
        if price is not None:
            body['price'] = float(price)
        if stop_price is not None:
            body['stopPrice'] = float(stop_price)

        r = self.client.post(
            f'{base}/order/placeorder',
            json=body,
            headers=self._headers_json(token),
            timeout=30,
        )
        print_http_trace(f"v1 placeorder · {order_type}", r.status_code, r.text or "")
        r.raise_for_status()
        return r.json() if r.text else {}

    def _execute(
        self,
        token: str,
        base_url: str,
        *,
        tv_account: str,
        side: str,
        instrument: str,
        order_qty: int,
        current_bid: float,
        current_ask: float,
        stop_loss: float | None = None,
        take_profit_1: float | None = None,
        take_profit_2: float | None = None,
        tp1_qty: int | None = None,
        tp2_qty: int | None = None,
        account_id: int | None = None,
        account_spec: str | None = None,
        v1_symbol: str | None = None,
        duration_type: str = 'Day',
        fill_wait_seconds: float = 1.5,
    ):
        """
        1) Market via TV demo bridge (same shape as your browser capture).
        2) Optional SL + TP(s) via standard v1 /order/placeorder (needs account_id
           + account_spec from /account/list). Use ``v1_symbol`` if Tradovate v1
           uses a different symbol string than ``instrument``.

        If both take-profit prices are set, you must pass ``tp1_qty`` and ``tp2_qty``
        so they sum to ``order_qty`` (exchange minimums apply).
        """
        entry = self._normalize_side_tv(side)
        out = {'market': self._tv_market_order(
            token,
            tv_account,
            instrument=instrument,
            qty=order_qty,
            side=entry,
            current_bid=current_bid,
            current_ask=current_ask,
            duration_type=duration_type,
        )}

        need_brackets = (
            stop_loss is not None
            or take_profit_1 is not None
            or take_profit_2 is not None
        )
        if not need_brackets:
            return out

        if account_id is None or not account_spec:
            raise ValueError(
                'stop_loss / take-profit require account_id and account_spec from v1 /account/list'
            )

        sym = v1_symbol or instrument
        ex = self._exit_action(entry)
        time.sleep(fill_wait_seconds)

        if stop_loss is not None:
            out['stop_loss'] = self._v1_place_order(
                token,
                base_url,
                account_id=account_id,
                account_spec=account_spec,
                symbol=sym,
                action=ex,
                order_qty=order_qty,
                order_type='Stop',
                stop_price=stop_loss,
            )

        if take_profit_1 is not None and take_profit_2 is not None:
            if tp1_qty is None or tp2_qty is None:
                raise ValueError(
                    'With two take-profit levels, pass tp1_qty and tp2_qty (must sum to order_qty).'
                )
            if int(tp1_qty) + int(tp2_qty) != int(order_qty):
                raise ValueError('tp1_qty + tp2_qty must equal order_qty')

            out['take_profit_1'] = self._v1_place_order(
                token,
                base_url,
                account_id=account_id,
                account_spec=account_spec,
                symbol=sym,
                action=ex,
                order_qty=int(tp1_qty),
                order_type='Limit',
                price=float(take_profit_1),
            )
            out['take_profit_2'] = self._v1_place_order(
                token,
                base_url,
                account_id=account_id,
                account_spec=account_spec,
                symbol=sym,
                action=ex,
                order_qty=int(tp2_qty),
                order_type='Limit',
                price=float(take_profit_2),
            )
        elif take_profit_1 is not None:
            out['take_profit_1'] = self._v1_place_order(
                token,
                base_url,
                account_id=account_id,
                account_spec=account_spec,
                symbol=sym,
                action=ex,
                order_qty=order_qty,
                order_type='Limit',
                price=float(take_profit_1),
            )

        return out

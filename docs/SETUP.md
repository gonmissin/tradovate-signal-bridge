# Tradovate Client — Full setup guide

This project runs a **Flask webhook** that turns JSON signals into:

1. A **TradingView demo** market order (`tv-demo.tradovateapi.com`).
2. **Tradovate v1** bracket orders: stop-loss and one or two take-profit limits (`demo.tradovateapi.com/v1`).
3. A **background watcher** (every **5 seconds**) that moves stop to **break-even** after TP1 (when you use a runner + TP2), cancels TPs if the stop hits first, and cleans up when BE or TP2 hits.

---

## 1. Requirements

- **Python 3.10+** (3.11+ recommended).
- **Windows Terminal** or another terminal that supports ANSI colors (optional, for `main.py` UI).
- A **Tradovate demo** login (same credentials you use in the trader web app).
- Your **TV demo account id** (the `D…` style id used in TradingView’s Tradovate bridge, e.g. `D45219551`).

Install dependencies from the project root:

```bash
pip install -r requirements.txt
```

Optional — regenerate the printable **signal flow PDF** (needs `fpdf2`):

```bash
pip install fpdf2
python scripts/generate_signal_flow_pdf.py
```

Output: `docs/Signal_Process.pdf` (also committed after generation). The **interactive** diagram is `docs/signal-flow.html` (open in a browser; click nodes, Tab-focus; Ctrl+P to print or save as PDF for another view).

---

## 2. Project layout (what actually matters)

| Path | Role |
|------|------|
| `app.py` | Flask app: `/webhook`, `/health`; starts trade watcher on first request. |
| `main.py` | Terminal UI: guided **first-time setup** and optional test trade (writes `assets/config.json`). |
| `assets/config.json` | **Single source of truth** for Flask + CLI: connection, order sizes, instruments, webhook flags (edited by `main.py` or by hand). TV bridge bid/ask placeholders live in code (`modules/client_config.py`). |
| `modules/auth.py` | Demo login → JWT used for v1 and TV bridge. |
| `modules/orders.py` | TV market POST + v1 `placeorder` + `order/list` + `cancelorder`. |
| `modules/client_config.py` | Loads `assets/config.json`. |
| `modules/trade_watch.py` | 5s poll: TP1 → BE, SL → cancel TPs, BE → cancel TP2, TP2 → cancel stop. |
| `docs/SETUP.md` | This guide. |
| `docs/signal-flow.html` | Interactive signal / execution flowchart. |
| `docs/Signal_Process.pdf` | Generated overview (run script above). |

Scratch helpers (`pending.py`, `id.py`) were removed; do not commit live JWTs or passwords.

---

## 3. First-time configuration (`main.py`)

From the project root:

```bash
python main.py
```

Use the menu to:

1. Set **username** and **password** (Tradovate demo).
2. Set **`tv_account`** (your `D…` id).
3. Set **order_qty**, **tp1_qty**, **tp2_qty**, and **instruments** (`tv` / optional `v1`).
4. Answer **two webhook prompts**: **two take-profits** (runner / BE path) and **skip when `regimeSuppressed`**.

This writes **`assets/config.json`**. **`app.py` reads only this file** on each request (via `modules/client_config.py`).

---

## 4. Webhook tuning (`assets/config.json` → `order`)

All of this lives under the **`order`** object unless noted:

| Key | Purpose |
|-----|---------|
| `place_two_tps` | If `true`, and the signal has both TP1 and target prices, place **two** v1 limits (sizes from `tp1_qty` / `tp2_qty`; must sum to `order_qty`). |
| `skip_when_regime_suppressed` | If `true`, skip trades when the JSON body has `regimeSuppressed` set. |
| `fill_wait_seconds` | Pause after market fill before v1 brackets (default `1.5`). |
| `instruments.nq` / `instruments.gc` | `tv` and optional `v1` symbols for signals mapped to that family (NQ/MNQ → `nq`, GC/MGC → `gc`). |
| `test_auto_flatten_seconds` | **Menu market test only:** after entry, wait this many seconds then send an **opposite-side** TV market order with the **same** `order_qty` to flatten. Set to `0` to disable. |

TV market **bid/ask** form fields are **not** in config: edit **`TV_BRIDGE_BID_ASK`** in `modules/client_config.py` (`nq` / `gc` families).

**`connection`** holds `username`, `password`, and **`tv_account`** (required for TV bridge). Optional **`v1_account_id`** (integer) and **`v1_account_spec`** (account name string for v1 `placeorder`) force the v1 account if auto-discovery fails (common with some prop org layouts).

At the **root** of `config.json`, **`developer_mode`** (`true` / `false`) controls whether full JSON bodies are printed for login and HTTP traces; when `false`, the terminal shows short colored status lines only.

---

## 5. Running the executor

```bash
python app.py
```

Defaults: `http://0.0.0.0:5000` (all interfaces), **threaded** mode.

- **Health:** `GET http://localhost:5000/health` → `{"ok": true}`.
- **Signal:** `POST http://localhost:5000/webhook` with `Content-Type: application/json`.

The **trade watcher** thread starts on the **first HTTP request** to the app (any route). It reuses the same cached login as the webhook.

### Exposing the webhook

Use **ngrok**, **Cloudflare Tunnel**, or your VPS reverse proxy to publish `5000` with **HTTPS** if your signal source requires it. Restrict by IP or secret header in production (not implemented in this repo — add your own middleware if needed).

---

## 6. Signal JSON (what the webhook expects)

Only **`action: "ENTRY"`** is executed (other actions return skipped or error depending on field presence).

Important fields:

| Field | Purpose |
|--------|---------|
| `action` | Must be `"ENTRY"` (or under `raw.action`). |
| `direction` | `"bullish"` → buy, `"bearish"` → sell. |
| `instrument` | e.g. `NQ`, `MNQ`, `GC`, `MGC` — mapped via `order.instruments` (`nq` / `gc` families). |
| `regimeSuppressed` | If `order.skip_when_regime_suppressed` is true → skip trade. |
| Stop / TP prices | From `app_stop`, `stop`, `appLevels.sl_*`, `app_tp1`, `tp1`, `app_target`, `target`, `appLevels.tp1`, `appLevels.tp2`, etc. (see `signal_to_execution_params` in `app.py`). |

Sizes come from **`assets/config.json`** (`order_qty`, `tp1_qty`, `tp2_qty`), not from the JSON body. With **`order.place_two_tps`** true, **tp1 + tp2** must equal **`order_qty`**.

---

## 7. Execution pipeline (short)

1. **Auth** — Selenium opens the web trader (same flow as `enable.py`), captures the `/auth/accesstokenrequest` JSON, caches the JWT. Requires **Chrome** + `selenium`. Set **`TRADOVATE_SELENIUM_HEADED=1`** for a visible browser if headless fails.
2. **Account** — Resolved from v1 only when the signal includes SL/TP (brackets). Market-only entries use the TV bridge only (`tv_account` in the URL). Optional `v1_account_id` / `v1_account_spec` override discovery.
3. **Market** — TV `POST .../accounts/{tv}/orders` (type `market`, bid/ask from `TV_BRIDGE_BID_ASK` in `client_config.py`).
4. **Brackets** — v1 `POST /order/placeorder` for stop and limit(s).
5. **Register** — Order ids parsed from placeorder responses → `TradeWatchManager`.
6. **Every 5s** — v1 `GET /order/list`; apply BE / cancel rules (see `modules/trade_watch.py`).

If **`placeorder` responses do not include a parseable `orderId`**, the watcher cannot register that bracket — check the JSON printed in the console and extend `Orders.place_response_order_id` if your environment differs.

---

## 8. v1 symbol vs TV symbol

TV market uses the **bridge** symbol (e.g. `MGCJ6`). v1 brackets use **`v1_symbol`** from config if set; otherwise the same string as the TV instrument. If v1 rejects the contract, set `order.instruments.<family>.v1` to the exact v1 symbol your account expects.

---

## 9. Security checklist

- Keep **`assets/config.json`** out of public repos (passwords, account ids).
- Rotate passwords if they were ever committed or shared.
- Do not paste **Bearer tokens** into random scripts; use `main.py` / `Auth` login only.

---

## 10. Troubleshooting

| Symptom | Things to check |
|---------|-------------------|
| `401` / login errors | `connection.username` / `password` in `config.json`; demo vs live host in `modules/auth.py`. |
| Missing instrument | `order.instruments.<nq|gc>.tv` and signal `instrument` key. |
| TV market rejects bid/ask | Rare; adjust `TV_BRIDGE_BID_ASK` in `modules/client_config.py`. |
| `tp1_qty + tp2_qty` error | `order.place_two_tps` true: quantities must sum to `order_qty`. |
| Watcher does nothing | Console should show `[watch] registered ...` after a trade; if not, fix `place_response_order_id` / API responses. |
| Wrong account | `tv_account` for TV only; v1 uses first account from `/account/list` — adjust account selection in code if you use multiple accounts. |

---

## 11. Related files

- **Interactive flow:** open `docs/signal-flow.html` in a browser (click nodes for details).
- **PDF flow:** run `python scripts/generate_signal_flow_pdf.py` → `docs/Signal_Process.pdf`.

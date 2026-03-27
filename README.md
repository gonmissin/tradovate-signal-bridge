# Tradovate × TradingView signal client

Python tooling that logs into **Tradovate** (browser capture → JWT), sends **TradingView demo bridge** market orders, optionally attaches **Tradovate v1** stop/limit brackets, and runs a small **background watcher** (break-even / TP cleanup).

## What it does

- **`main.py`** — First-run wizard, writes `assets/config.json`, **market test** (optional auto-flatten below).
- **`app.py`** — Flask **`POST /webhook`** to execute signals from JSON (e.g. your strategy server).
- **`enable.py`** — Standalone Selenium login + token capture (debug / inspection).
- **TV bridge** — `POST https://tv-demo.tradovateapi.com/accounts/{tv_account}/orders` (same JWT as v1 demo).
- **v1** — `POST …/order/placeorder` for stops/limits when the signal includes SL/TP levels (needs resolvable v1 account when brackets are used).

**TV bridge bid/ask (placeholders)**

The TradingView demo market POST requires `currentBid` / `currentAsk`. This project uses **fixed placeholders** in `modules/client_config.py` (`TV_BRIDGE_BID_ASK` for `nq` and `gc`). Edit that dict if you need different numbers; they are not read from `config.json`.

**Test signal (menu market test) auto-flatten**

After a test **buy** of **N** contracts, the client waits `order.test_auto_flatten_seconds` (default **5**), then sends **N** contracts **sell** (and the reverse for a test sell). Set `test_auto_flatten_seconds` to **0** to disable. Flatten uses the **same** static bid/ask as the entry.

---

## Quick start

```bash
pip install -r requirements.txt
python main.py    # setup + optional market test; creates assets/config.json
python app.py     # webhook on http://0.0.0.0:5000
```

- **Health:** `GET /health`
- **Trade:** `POST /webhook` with `Content-Type: application/json`

Full walkthrough, security, payload fields, and troubleshooting: **[docs/SETUP.md](docs/SETUP.md)**.

---

## Configuration highlights

| Location | Notes |
|----------|--------|
| Root `developer_mode` | `true` → print full JSON for login/API traces; `false` → short colored lines. |
| `connection.tv_account` | TV bridge id (e.g. `D45219551`). |
| `connection.username` / `password` | Tradovate demo (Selenium login). |
| `connection.v1_account_id` / `v1_account_spec` | Optional; only needed when placing v1 brackets if auto-discovery fails. |
| `order.test_auto_flatten_seconds` | Menu test only: seconds before opposite-side market flatten (`0` = off). |

---

## Docs & diagrams

- **[docs/SETUP.md](docs/SETUP.md)** — Full setup guide.
- **[docs/signal-flow.html](docs/signal-flow.html)** — Open in a browser for an interactive flowchart.
- **[docs/Signal_Process.pdf](docs/Signal_Process.pdf)** — Overview PDF; regenerate: `python scripts/generate_signal_flow_pdf.py`.

---

## Security (before you push to GitHub)

- This repo includes a **`.gitignore`** that excludes `assets/config.json` so local credentials stay off GitHub by default. Copy fields from a private backup when cloning on a new machine, or run `python main.py` again to recreate config.
- **Do not commit** real passwords or Bearer tokens.
- Rotate credentials if they were ever committed or pasted in chat.
- Prefer environment variables or a secrets manager for production (not built into this repo).

---

## Requirements

- Python **3.10+** (3.11+ recommended)
- **Google Chrome** (for Selenium login)
- See **`requirements.txt`**

---

## License

No license file is set by default; add one (e.g. MIT) when you publish if you want explicit terms.

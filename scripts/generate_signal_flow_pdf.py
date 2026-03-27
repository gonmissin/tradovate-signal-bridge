#!/usr/bin/env python3
"""
Build docs/Signal_Process.pdf - overview + clickable TOC (internal links).
Requires: pip install fpdf2
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "docs" / "Signal_Process.pdf"


class FlowPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(130, 140, 160)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _rgb(pdf: FPDF, r: int, g: int, b: int) -> None:
    pdf.set_text_color(r, g, b)


def main() -> None:
    pdf = FlowPDF(format="Letter")
    pdf.set_auto_page_break(True, margin=20)
    pdf.set_margins(20, 20, 20)

    navy = (32, 56, 92)
    body = (55, 65, 85)
    muted = (120, 130, 155)
    accent = (0, 140, 125)

    # --- Page 1: cover + TOC (links to pages 2–6)
    pdf.add_page()
    top_link = pdf.add_link()
    pdf.set_link(top_link, page=1)

    pdf.set_font("Helvetica", "B", 24)
    _rgb(pdf, *navy)
    pdf.cell(0, 14, "Tradovate Client", ln=True, align="C")
    pdf.set_font("Helvetica", "", 14)
    _rgb(pdf, *body)
    pdf.cell(0, 10, "Signal process", ln=True, align="C")
    pdf.set_font("Helvetica", "I", 11)
    _rgb(pdf, *muted)
    pdf.cell(0, 8, "Webhook + TV market + v1 brackets + 5s trade watch", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Helvetica", "B", 12)
    _rgb(pdf, *navy)
    pdf.cell(0, 8, "Linear flow (read top to bottom)", ln=True)
    pdf.set_font("Courier", "", 9)
    _rgb(pdf, *body)
    lines = [
        "POST /webhook (JSON)",
        "  -> filter ENTRY / map instrument / placeholder bid·ask / sizes",
        "  -> Auth JWT (cached) + v1 account/list",
        "  -> TV market order (tv-demo bridge)",
        "  -> v1 placeorder: Stop + Limit (TP1 [, TP2])",
        "  -> register order ids -> TradeWatchManager",
        "  -> every 5s: GET order/list -> TP1/SL/TP2 rules",
    ]
    for line in lines:
        pdf.cell(0, 5, line, ln=True)
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 12)
    _rgb(pdf, *navy)
    pdf.cell(0, 8, "Clickable sections (PDF reader)", ln=True)
    pdf.set_font("Helvetica", "", 11)

    toc = [
        ("1. Webhook & JSON mapping", 2),
        ("2. Execution: market + v1 brackets", 3),
        ("3. Trade watch (5 seconds)", 4),
        ("4. Outcomes: TP1, stop, TP2", 5),
        ("5. Configuration & runbook", 6),
    ]
    toc_links: list[tuple[str, int, int]] = []
    for label, page in toc:
        lk = pdf.add_link()
        toc_links.append((label, page, lk))
    for label, page, lk in toc_links:
        pdf.set_link(lk, page=page)
        _rgb(pdf, *accent)
        pdf.cell(0, 9, label, ln=True, link=lk)

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 9)
    _rgb(pdf, *muted)
    pdf.multi_cell(
        0,
        5,
        "For a fully interactive diagram (hover + scroll), open docs/signal-flow.html in a browser.",
    )

    # --- Section pages
    def section_page(title: str, bullets: list[str]) -> None:
        pdf.add_page()
        bl = pdf.add_link()
        pdf.set_link(bl, page=1)
        pdf.set_font("Helvetica", "U", 10)
        _rgb(pdf, *accent)
        pdf.cell(0, 8, "Back to overview", ln=True, link=bl)
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 16)
        _rgb(pdf, *navy)
        pdf.cell(0, 10, title, ln=True)
        pdf.set_font("Helvetica", "", 11)
        _rgb(pdf, *body)
        for b in bullets:
            pdf.multi_cell(0, 6, f"- {b}")
            pdf.ln(1)

    section_page(
        "1. Webhook & JSON mapping",
        [
            "Flask route POST /webhook in app.py; GET /health for probes.",
            'Only action "ENTRY" is executed; direction bullish/bearish maps to buy/sell.',
            "Instrument (NQ, GC, ...) resolves TV + optional v1 symbol via assets/config.json only.",
            "Stop / TP prices from body fields and appLevels; sizes from config order_qty, tp1_qty, tp2_qty.",
            "entry_price for break-even uses ask on buys and bid on sells at signal time.",
        ],
    )
    section_page(
        "2. Execution: market + v1 brackets",
        [
            "modules/orders.py: TV POST to tv-demo.tradovateapi.com/accounts/{tv}/orders (market).",
            "After fill_wait_seconds, v1 POST .../order/placeorder for Stop and Limit legs.",
            "Two take-profits require order.place_two_tps in config.json and tp1_qty + tp2_qty == order_qty.",
            "place_response_order_id parses bracket responses so the watcher can track ids.",
        ],
    )
    section_page(
        "3. Trade watch (5 seconds)",
        [
            "modules/trade_watch.py runs in a daemon thread started on first HTTP request.",
            "Each poll (every 5 seconds): GET demo.tradovateapi.com/v1/order/list, match ordStatus for registered ids.",
            "POST /order/cancelorder to remove stale limits/stops; optional new stop at BE for runner size.",
        ],
    )
    section_page(
        "4. Outcomes: TP1, stop, TP2",
        [
            "TP1 filled: cancel working stop; if runner (tp2_qty > 0) place BE stop at entry for runner qty.",
            "Stop filled before BE move: cancel TP1 and TP2 if still working.",
            "Stop filled after BE move: cancel TP2 only.",
            "TP2 filled: cancel working stop (flat at target).",
            "Single TP (no runner): after TP1, cancel stop and drop watch.",
        ],
    )
    section_page(
        "5. Configuration & runbook",
        [
            "Run python main.py once to build assets/config.json (credentials, tv_account, instruments).",
            "pip install -r requirements.txt then python app.py (default port 5000).",
            "See docs/SETUP.md for troubleshooting, security, and webhook payload reference.",
        ],
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()

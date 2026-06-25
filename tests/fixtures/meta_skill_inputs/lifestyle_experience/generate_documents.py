#!/usr/bin/env python3
"""Generate binary lifestyle meta-skill fixtures.

The text fixtures in this directory are committed directly. This script keeps
PDF, DOCX, and XLSX examples reproducible without requiring the gateway to
download anything during manual WebUI testing.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent


def make_travel_pdf() -> None:
    target = ROOT / "travel_admin_pack"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "japan_trip_notes.pdf"

    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 72
    lines = [
        "Japan Family Trip Notes",
        "",
        "Travelers: parents, first self-managed international mobile data setup.",
        "Dates: 8 days in June 2026.",
        "Route: Tokyo arrival, Osaka departure.",
        "Main phone uses: WeChat, maps, translation, occasional video calls.",
        "Priority: stable and simple setup; budget should stay reasonable.",
        "Open items:",
        "- Choose travel eSIM, carrier roaming, or local SIM.",
        "- Prepare setup instructions before departure.",
        "- Keep hotel, passport, insurance, and emergency contacts together.",
        "- Add reminders for activation, data test, and offline maps.",
    ]
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()


def make_finance_xlsx() -> None:
    target = ROOT / "personal_finance_radar"
    target.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Watchlist"
    rows = [
        ("Ticker", "Asset", "Why watching", "Risk to monitor", "My note"),
        (
            "NVDA",
            "NVIDIA",
            "AI data-center demand",
            "Valuation and export controls",
            "Do not chase only price action",
        ),
        (
            "TSLA",
            "Tesla",
            "Delivery and autonomy narrative",
            "Margin pressure and execution",
            "High volatility",
        ),
        (
            "AAPL",
            "Apple",
            "Services and device cycle",
            "China demand and regulation",
            "Quality defensive name",
        ),
        (
            "BTC",
            "Bitcoin",
            "Macro liquidity and ETF flows",
            "Drawdown risk and leverage",
            "Position sizing matters",
        ),
    ]
    for row in rows:
        ws.append(row)
    for col in "ABCDE":
        ws.column_dimensions[col].width = 28
    wb.save(target / "watchlist.xlsx")


def main() -> None:
    make_travel_pdf()
    make_finance_xlsx()


if __name__ == "__main__":
    main()

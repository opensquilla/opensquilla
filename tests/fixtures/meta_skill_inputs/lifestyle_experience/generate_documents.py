#!/usr/bin/env python3
"""Generate binary lifestyle meta-skill fixtures.

The text fixtures in this directory are committed directly. This script keeps
PDF, DOCX, and XLSX examples reproducible without requiring the gateway to
download anything during manual WebUI testing.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent


def make_vendor_docs() -> None:
    target = ROOT / "document_vendor_decision"
    target.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Quote A"
    rows = [
        ("Field", "Value"),
        ("Vendor", "Acme DailyOps Cloud"),
        ("Annual service fee", "RMB 18,600"),
        ("Payment due", "2026-06-03"),
        ("Seats included", "20"),
        ("Overage", "RMB 120 per extra seat per month"),
        ("Billing contact", "finance@acme-dailyops.example"),
    ]
    for row in rows:
        ws.append(row)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 42
    wb.save(target / "vendor_quote_a.xlsx")

    doc = Document()
    doc.add_heading("Service Renewal Contract Excerpt", level=1)
    doc.add_paragraph("Vendor: Acme DailyOps Cloud")
    doc.add_paragraph("Customer: Example Operations Team")
    doc.add_paragraph(
        "The subscription renews automatically for another twelve months unless "
        "the customer sends written cancellation notice at least 30 days before "
        "the renewal effective date."
    )
    doc.add_paragraph(
        "If the customer cancels after the notice window, the vendor may charge "
        "a cancellation penalty equal to 30% of the annual service fee."
    )
    doc.add_paragraph(
        "The excerpt does not state the current contract end date or the renewal "
        "effective date."
    )
    doc.save(target / "contract_excerpt.docx")


def make_family_doc() -> None:
    target = ROOT / "family_school_errand_day"
    target.mkdir(parents=True, exist_ok=True)

    doc = Document()
    doc.add_heading("Kindergarten Notice", level=1)
    doc.add_paragraph("Class: Sunflower Class")
    doc.add_paragraph("Tomorrow each child should bring a raincoat and one family photo.")
    doc.add_paragraph("Dropoff should be completed before 08:15. Pickup is at 17:00.")
    doc.add_paragraph("Food safety note: one child in the class is allergic to peanuts.")
    doc.save(target / "kindergarten_notice.docx")


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
        ("NVDA", "NVIDIA", "AI data-center demand", "Valuation and export controls", "Do not chase only price action"),
        ("TSLA", "Tesla", "Delivery and autonomy narrative", "Margin pressure and execution", "High volatility"),
        ("AAPL", "Apple", "Services and device cycle", "China demand and regulation", "Quality defensive name"),
        ("BTC", "Bitcoin", "Macro liquidity and ETF flows", "Drawdown risk and leverage", "Position sizing matters"),
    ]
    for row in rows:
        ws.append(row)
    for col in "ABCDE":
        ws.column_dimensions[col].width = 28
    wb.save(target / "watchlist.xlsx")


def main() -> None:
    make_vendor_docs()
    make_family_doc()
    make_travel_pdf()
    make_finance_xlsx()


if __name__ == "__main__":
    main()

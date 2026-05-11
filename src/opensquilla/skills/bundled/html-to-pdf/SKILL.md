---
name: html-to-pdf
description: "Render HTML (with CSS) to a PDF file. Trigger when the user wants to export a styled report, invoice, label, or any HTML/Jinja-rendered page to PDF. Uses WeasyPrint, which supports a meaningful subset of CSS Paged Media (page size, margins, headers/footers, page-break-before/after). Optional dependency — install via `pip install opensquilla[document-extras]` or `uv add weasyprint` because WeasyPrint pulls in native libraries (Pango, Cairo, fontconfig) that need OS-level packages."
homepage: https://weasyprint.org/
provenance:
  origin: clawhub-mit0
  license: MIT-0
  upstream_url: https://clawhub.ai/generate-pdf
  maintained_by: OpenSquilla
metadata:
  {
    "platform":
      {
        "emoji": "📄",
        "requires": { "anyBins": ["python", "python3"] },
        "install":
          [
            {
              "id": "weasyprint",
              "kind": "uv",
              "package": "weasyprint",
              "label": "Install WeasyPrint (uv pip)",
            },
          ],
      },
  }
---

# html-to-pdf

Render HTML + CSS to PDF using WeasyPrint. Best for static report exports
where the source already exists in HTML form (templates, dashboards,
invoices). For programmatic PDF assembly from data structures, use the
`pdf-toolkit` skill's reportlab path instead.

## Delivery rule

When the user asks for a PDF, report, printable page, or finished HTML export,
write the final file in the workspace. If the `publish_artifact` tool is
available, call it for the final `.pdf` or requested file before your final
reply. Do not paste the full HTML/CSS source into chat as a substitute for
delivering the file unless the user explicitly asks for source code.

## When to use

- HTML/Jinja template + content → styled PDF report
- Markdown rendered to HTML → printable PDF
- Email content → archival PDF
- Generated dashboards (HTML + screenshots) → shareable PDF

## When NOT to use

- Source data is structured (JSON, dataframe) and there is no HTML —
  use `pdf-toolkit` (reportlab) directly.
- Source PDF needs editing — use `pdf-toolkit` (pypdf path).
- Need pixel-perfect Word-style document layout — use the `docx` skill.
- Need to render dynamic JavaScript-driven content — WeasyPrint does not
  execute JS. Pre-render the page with a headless browser first.

## Quick start

```bash
python {baseDir}/scripts/render.py --html report.html --out report.pdf
python {baseDir}/scripts/render.py --html invoice.html --out invoice.pdf --page-size A4
```

The script accepts a local file path, a `file://` URL, or an `http(s)://`
URL. CSS is loaded relative to the HTML location for local paths; for
URLs, the same fetch rules apply (network resources are loaded with
WeasyPrint's default fetcher).

## CSS Paged Media support

WeasyPrint implements the parts of CSS that matter for paged output:

- `@page` rule with `size`, `margin`, `@top-center`, `@bottom-right` boxes
- Page breaks: `page-break-before`, `page-break-after`, `break-inside: avoid`
- Counters: `counter(page)`, `counter(pages)`
- `prince-` properties: WeasyPrint supports many but not all PrinceXML
  extensions

Example header/footer setup:

```css
@page {
  size: Letter;
  margin: 1in;
  @top-center { content: "Q3 Review — Confidential"; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); }
}
```

## Cross-platform install hints

WeasyPrint is pure Python but depends on native libraries. The OpenSquilla
install spec only triggers `pip install weasyprint`; the OS packages must
be installed separately.

### macOS

```bash
brew install pango cairo gdk-pixbuf libffi
```

### Debian/Ubuntu

```bash
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 \
    libharfbuzz0b libfontconfig1
```

### Windows

The simplest path is the GTK runtime via winget:

```powershell
winget install --id GTK.GTK3
```

Or use MSYS2's `mingw-w64-x86_64-pango` package and ensure its `bin/`
directory is on `PATH`. WeasyPrint ≥61 ships an alternate "lite" path that
bundles its own native libs on Windows; check WeasyPrint's installation
docs for the current state.

If the `render.py` script raises `OSError: cannot load library`, the
native libs are not on the search path — the user must install them per
the platform instructions above.

## Boundaries

- Does not execute JavaScript. Pre-render dynamic content with a headless
  browser first, then feed the resulting HTML to this skill.
- Does not support every CSS feature — flexbox and grid have known
  limitations in paged contexts. Test layout before relying on either.
- Font availability is OS-dependent. To guarantee reproducibility, embed
  fonts via `@font-face` with absolute paths or data URIs.
- For high-volume PDF generation (hundreds of documents per minute),
  prefer a service-grade renderer (PrinceXML, browser-based pipelines).
  WeasyPrint is the right tool for tens to a few hundred PDFs per run.

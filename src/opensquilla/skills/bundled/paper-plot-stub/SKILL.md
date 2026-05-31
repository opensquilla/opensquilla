---
name: paper-plot-stub
description: "Plot a results CSV (x, y_baseline, y_ours) as a two-line matplotlib chart and write a PDF. Demo-only."
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  {
    "platform": {
      "emoji": "📈",
      "requires": { "anyBins": ["python", "python3"] }
    }
  }
entrypoint:
  command: python {baseDir}/scripts/plot.py
  args:
    - "paper/results.csv"
    - --out
    - "paper/figure_1.pdf"
  parse: text
  timeout: 30
---

# paper-plot-stub

Reads a CSV with columns `x, y_baseline, y_ours` and writes a two-line
plot as PDF. matplotlib is required at runtime.

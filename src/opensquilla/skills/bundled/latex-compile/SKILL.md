---
name: latex-compile
description: "Compile a LaTeX project (xelatex × bibtex × xelatex × xelatex) and report the log tail. Demo-only."
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  {
    "platform": {
      "emoji": "📄",
      "requires": { "anyBins": ["xelatex"] }
    }
  }
entrypoint:
  command: python {baseDir}/scripts/compile.py
  args:
    - "paper/paper.tex"
  assemble:
    - into: "paper/paper.tex"
      from_template: |
        \documentclass[11pt]{article}
        \usepackage[utf8]{inputenc}
        \usepackage{graphicx}
        \usepackage{hyperref}
        \title{ {{ inputs.user_message | truncate(80) }} }
        \author{OpenSquilla meta-paper-write}
        \date{\today}
        \begin{document}
        \maketitle
        {{ outputs.draft_abstract }}
        {{ outputs.draft_intro }}
        {{ outputs.draft_method }}
        {{ outputs.draft_results }}
        {{ outputs.draft_discussion }}
        \bibliographystyle{plain}
        \bibliography{references}
        \end{document}
  parse: text
  timeout: 120
---

# latex-compile

Compile a 5-section LaTeX paper assembled from upstream meta-skill step
outputs. The orchestrator renders `paper.tex` via the `entrypoint.assemble`
block, then this script runs xelatex / bibtex / xelatex × 2.

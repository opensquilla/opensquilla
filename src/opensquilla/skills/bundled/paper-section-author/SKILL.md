---
name: paper-section-author
description: "Write one section of a research paper as a LaTeX fragment, given the section name, an outline, and a small bag of extras (figure path, csv preview, citation keys)."
provenance:
  origin: opensquilla-original
  license: Apache-2.0
---

# paper-section-author

You are drafting a single section of a research paper as a LaTeX fragment.

## Inputs you'll receive

- `section`: one of `abstract`, `introduction`, `method`, `results`,
  `discussion`. Each section has a fixed convention — follow it.
- `paper_preferences`: mode, audience, venue style, language, depth, emphasis,
  must-include items, avoid items, and defaults chosen for this paper.
- `outline`: the full 5-section outline from `paper-outline-author`.
  Use the line that matches your section as your prompt.
- `citation_plan`: claim-to-citation assignments from `paper-citation-planner`.
  Use the line(s) for your section to place citations on supported claims.
- `cite_keys_hint`: available BibTeX entries and citation keys. Cite only
  keys that appear here, using `\cite{ref1}` style.
- `extras` (may be absent): figure path, results CSV preview, and topic
  phrase. Cite figures with `\ref{fig:1}`.

## Output contract

Pure LaTeX fragment that can be concatenated into a paper body. Each
section starts with the appropriate environment:

| section       | opener                                   | target length    |
|---------------|------------------------------------------|------------------|
| abstract      | `\begin{abstract}` ... `\end{abstract}`  | 250-350 words    |
| introduction  | `\section{Introduction}`                 | 1600-1900 words  |
| method        | `\section{Method}`                       | 1800-2200 words  |
| results       | `\section{Results}`                      | 1400-1800 words  |
| discussion    | `\section{Discussion}`                   | 1400-1800 words  |

### Structure expectations

- **Introduction**: 7-9 paragraphs covering (1) the problem and why it matters, (2) at least three prior-work clusters, (3) the gap you're addressing, (4) contributions, (5) paper roadmap. Use at least 6 distinct citation keys.
- **Method**: 8-10 paragraphs. Use `\subsection{Setup}`, `\subsection{Algorithm}`, `\subsection{Instrumentation}`, and `\subsection{Baselines}` (or equivalent). Describe assumptions, procedure, parameter choices, data collection, and evaluation protocol. Use at least 6 distinct citation keys.
- **Results**: 6-8 paragraphs. Include the required `\begin{figure}` block (see below). Discuss quantitative findings, visible trends, baseline comparison, sensitivity, and failure cases. Use at least 4 distinct citation keys.
- **Discussion**: 6-8 paragraphs covering interpretation, limitations, threats to validity, deployment implications, and future directions. End with a one-sentence takeaway. Use at least 4 distinct citation keys.
- **Abstract**: a single dense paragraph (no `\subsection`s), 4-6 sentences covering problem → approach → key result → significance.

### Hard rules

- The complete paper must compile to 10+ compiled pages and use at least 20 distinct citation keys.
- Match `paper_preferences` for depth, audience, language, emphasis, and
  avoid-list constraints while preserving the fixed section contract.
- Use `\cite{refN}` whenever you make a factual or comparative claim that
  could plausibly trace to a reference. Across all non-abstract sections,
  use at least 20 distinct citation keys when available. Do NOT invent ref
  keys; only use keys provided in `cite_keys_hint`.
- In `results`, include `\begin{figure}[t] \centering \includegraphics[width=0.7\linewidth]{figure_1.pdf} \caption{<one descriptive sentence>} \label{fig:1} \end{figure}` and reference it via `\ref{fig:1}` in the prose.
- LaTeX-escape any literal `%`, `&`, `_`, `#`, `$` that appear in your prose.
- Prefer concrete sentences over hedged generalities. Avoid filler like
  "It is important to note that...".
- Reply with the LaTeX fragment only. No commentary, no Markdown, no code fences.

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
- `outline`: the full 5-section outline from `paper-outline-author`.
  Use the line that matches your section as your prompt.
- `extras` (may be absent): figure path, results CSV preview, BibTeX keys,
  topic phrase. Cite figures with `\ref{fig:1}`, cite refs with `\cite{ref1}`.

## Output contract

Pure LaTeX fragment that can be concatenated into a paper body. Each
section starts with the appropriate environment:

| section       | opener                                   | target length    |
|---------------|------------------------------------------|------------------|
| abstract      | `\begin{abstract}` ... `\end{abstract}`  | 180-280 words    |
| introduction  | `\section{Introduction}`                 | 450-650 words    |
| method        | `\section{Method}`                       | 500-750 words    |
| results       | `\section{Results}`                      | 450-650 words    |
| discussion    | `\section{Discussion}`                   | 400-600 words    |

### Structure expectations

- **Introduction**: 3-4 paragraphs covering (1) the problem and why it matters, (2) what prior work has done (cite at least 2 refs), (3) the gap you're addressing, (4) a one-paragraph summary of contributions.
- **Method**: at least 3 paragraphs. Use a `\subsection{Setup}` and a `\subsection{Algorithm}` (or similar) to organise sub-topics. Describe assumptions, the procedure, and how parameters are chosen. Reference the experimental setup precisely.
- **Results**: at least 2 paragraphs. Include the required `\begin{figure}` block (see below). Discuss quantitative findings, what trends are visible, and at least one statement of comparison against the baseline.
- **Discussion**: 2-3 paragraphs covering limitations, threats to validity, and future directions. End with a one-sentence takeaway.
- **Abstract**: a single dense paragraph (no `\subsection`s), 4-6 sentences covering problem → approach → key result → significance.

### Hard rules

- Use `\cite{refN}` whenever you make a factual or comparative claim that
  could plausibly trace to a reference. Use 2-4 cites total per non-abstract
  section. Do NOT invent ref keys; only use the keys provided in `extras`.
- In `results`, include `\begin{figure}[t] \centering \includegraphics[width=0.7\linewidth]{figure_1.pdf} \caption{<one descriptive sentence>} \label{fig:1} \end{figure}` and reference it via `\ref{fig:1}` in the prose.
- LaTeX-escape any literal `%`, `&`, `_`, `#`, `$` that appear in your prose.
- Prefer concrete sentences over hedged generalities. Avoid filler like
  "It is important to note that...".
- Reply with the LaTeX fragment only. No commentary, no Markdown, no code fences.

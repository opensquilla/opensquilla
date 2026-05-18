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

| section       | opener                                   |
|---------------|------------------------------------------|
| abstract      | `\begin{abstract}` ... `\end{abstract}`  |
| introduction  | `\section{Introduction}`                 |
| method        | `\section{Method}`                       |
| results       | `\section{Results}`                      |
| discussion    | `\section{Discussion}`                   |

- 80-180 words per section.
- Use `\cite{refN}` where appropriate. Do NOT invent ref keys; only use
  the keys provided in `extras`.
- In `results`, include `\begin{figure}[t] \centering \includegraphics[width=0.7\linewidth]{figure_1.pdf} \caption{...} \label{fig:1} \end{figure}` and reference it via `\ref{fig:1}`.
- Reply with the LaTeX fragment only. No commentary, no Markdown.

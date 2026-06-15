# Meta-Skills

Meta-skills package repeatable multi-step work as reusable, inspectable
workflows. Use them when a request needs more than one normal skill, tool,
checkpoint, or final synthesis pass.

For the full user-facing guide, read
[`meta-skill-user-guide.md`](meta-skill-user-guide.md). For authoring rules,
read [`../authoring/meta-skills.md`](../authoring/meta-skills.md).

## Skills vs Meta-Skills

| Capability | Use it for |
| --- | --- |
| Skill | One focused task pattern, instruction set, script, or tool helper. |
| Meta-skill | A reusable workflow made of multiple steps, skills, checks, or outputs. |

For example, "summarize this document" is skill-shaped. "Plan a safe child
science project with materials, adult setup, child steps, presentation notes, and
final safety review" is meta-skill-shaped.

## Stable Built-In MetaSkills

The retained stable catalog is intentionally small:

| MetaSkill | Positioning |
| --- | --- |
| `meta-kid-project-planner` | Produces safe, age-appropriate plans for school projects, show-and-tell, or science activities. |
| `meta-paper-write` | Supports academic drafts, manuscript structure, citation planning, experiment placeholders, and LaTeX/PDF paths. |
| `meta-short-drama` | Produces short-drama scripts, visual prompts, subtitles, and local video artifacts. |
| `meta-skill-creator` | Turns repeated multi-skill collaboration patterns into new MetaSkill proposals. |

Experimental meta-skills may exist under development trees, but this page lists
only bundled built-ins that should be presented as retained product
capabilities.

## Requirements

Use the Skill page detail dialog before running a MetaSkill. Its
**Requirements** section shows the MetaSkill's own requirements plus one-hop
requirements from child skills.

- `meta-paper-write` needs `xelatex` and `bibtex` for PDF compilation.
- `meta-short-drama` needs `ffmpeg` and `ffprobe` for local video rendering,
  merge, and subtitle steps.
- MetaSkills inherit readiness from their child skills; for example,
  `meta-paper-write` surfaces LaTeX/PDF requirements and
  `meta-short-drama` surfaces local video-tool requirements.

## How to Ask

Ask for the outcome and the standard:

```text
Plan a safe 20-minute balcony plant science project for a 7-year-old. Include
materials, adult setup, child steps, safety notes, and a presentation outline.
```

For important or easily confused work, name the workflow:

```text
Use meta-skill `meta-kid-project-planner`.

Plan a safe 20-minute balcony plant science project for a 7-year-old. Include
materials, adult setup, child steps, safety notes, and a presentation outline.
```

A strong request usually includes:

- outcome;
- context;
- decision standard;
- expected output;
- constraints;
- actions the agent must not take.

## Discover Meta-Skills

List and search skills:

```sh
opensquilla skills list
opensquilla skills search meta
```

Inspect a meta-skill composition:

```sh
opensquilla skills inspect <meta-skill-name>
```

The inspect command shows the compiled step shape before you rely on a workflow.

## Inspect Run History

List recent runs:

```sh
opensquilla skills meta runs list
```

Inspect one run:

```sh
opensquilla skills meta runs show <run-id>
opensquilla skills meta runs steps <run-id>
opensquilla skills meta runs failures --since 24h
```

Preview replay shape without executing live work:

```sh
opensquilla skills meta runs replay <run-id> --dry-run
```

## Proposals

Meta-skill creation workflows may write proposals before they become managed
skills. Inspect proposals:

```sh
opensquilla skills meta proposals list
opensquilla skills meta proposals show <proposal-id>
```

Accept a proposal only after review:

```sh
opensquilla skills meta proposals accept <proposal-id>
```

## Safety Model

MetaSkill outputs are reviewable work products and decision-support drafts. They
are not final professional advice in legal, medical, financial, hiring,
academic, security, or other high-stakes contexts.

Actions such as publishing, applying, installing, paying, signing, messaging, or
modifying production systems require explicit user authorization.

---

[Docs index](../README.md) · [Product guide](../../README.product.md) · [Improve this page](../contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)

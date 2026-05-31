# Skills

Skills are task-specific instruction packages and scripts. They let OpenSquilla
load relevant guidance only when a task needs it, instead of putting every
possible instruction into every prompt.

Skills are separate from memory. Memory stores facts; skills describe repeatable
ways to work.

## What Skills Are For

Use skills for repeatable work patterns such as:

- deep research;
- summarization;
- GitHub and PR workflows;
- document generation;
- spreadsheet, slide, PDF, and DOCX work;
- web search;
- weather lookup;
- terminal or tmux monitoring;
- subagent delegation;
- skill creation and review.

If the workflow combines multiple skills or a reusable multi-step plan, use a
meta-skill instead.

## Discover Installed Skills

List skills available in the current install:

```sh
opensquilla skills list
```

View one skill:

```sh
opensquilla skills view <skill-name>
```

Search community sources:

```sh
opensquilla skills search pdf
```

Some skills may be ineligible when optional dependencies are missing or when the
skill is intentionally demo-only. `skills list` is the source of truth for your
current install.

## Install, Update, and Remove Skills

Install a managed skill:

```sh
opensquilla skills install <skill-name>
```

Update one skill or all managed skills:

```sh
opensquilla skills update <skill-name>
opensquilla skills update --all
```

Remove a managed skill:

```sh
opensquilla skills uninstall <skill-name>
```

## Manage Skill Sources

Custom source repositories are called taps:

```sh
opensquilla skills tap list
opensquilla skills tap add <owner/repo>
opensquilla skills tap remove <owner/repo>
```

Use taps when your team maintains its own skill catalog.

## Publish and Inspect

Publish a skill directory:

```sh
opensquilla skills publish <path-to-skill>
```

Inspect the compiled composition for a meta-skill:

```sh
opensquilla skills inspect <meta-skill-name>
```

For ordinary skill content, use:

```sh
opensquilla skills view <skill-name>
```

## How to Ask for a Skill

Ask for the outcome:

```text
Create a PowerPoint deck summarizing this report.
```

Better than:

```text
Load the pptx skill and run its script.
```

OpenSquilla can choose eligible skills from the current catalog when the task
matches their description and triggers.

## Bundled Skill Families

| Family | Examples |
| --- | --- |
| Research | deep research, multi-source search, summarization |
| Documents | DOCX, PPTX, XLSX, PDF, HTML-to-PDF |
| Operations | cron, GitHub, terminal monitoring, subagents |
| Memory | memory-oriented helpers and history exploration |
| Creation | skill creator, skill review, proposal helpers |

## Troubleshooting

If a skill is not selected:

1. Confirm it appears in the installed catalog:

   ```sh
   opensquilla skills list
   ```

2. Inspect its description and eligibility:

   ```sh
   opensquilla skills view <skill-name>
   ```

3. Ask for the outcome in normal language. Skill names can help, but user
   intent should still be clear.

4. If optional dependencies are missing, install or update the skill and retry.

For composed workflows, read [`meta-skills.md`](meta-skills.md). For the full
MetaSkill user guide, read [`meta-skill-user-guide.md`](meta-skill-user-guide.md).
For authoring rules, read [`../authoring/meta-skills.md`](../authoring/meta-skills.md).

---

[Docs index](../README.md) · [Product guide](../../README.product.md) · [Improve this page](../contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)

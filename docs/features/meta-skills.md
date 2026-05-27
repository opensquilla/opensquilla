# Meta-Skills

Meta-skills package repeatable multi-step work as reusable workflows. They are
for tasks that naturally combine skills, tools, routing, checkpoints, and final
synthesis.

Use this page when a normal skill is too small and a full custom integration is
too heavy.

## Skills vs Meta-Skills

| Capability | Use it for |
| --- | --- |
| Skill | One focused task pattern, instruction set, or tool helper. |
| Meta-skill | A reusable workflow made of multiple steps, skills, checks, or outputs. |

For example, "summarize a document" is a skill-shaped task. "Search the web,
collect sources, draft a report, render it as a PDF, and save the artifact" is
a meta-skill-shaped task.

## Good Fits

Use a meta-skill for:

- web research reports;
- PDF or slide briefings;
- current-diff review bundles;
- pre-commit quality gates;
- security or compliance review bundles;
- knowledge-base bootstrap;
- travel planning;
- long-running operational checks;
- repeatable document generation.

Avoid meta-skills for:

- one-off instructions;
- a single tool call;
- vague brainstorming with no stable workflow;
- workflows that need frequent manual redesign.

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

The inspect command is useful before relying on a workflow because it shows the
compiled step shape at a product level.

## Run Meta-Skills

Meta-skills are usually invoked by the agent when the user's request matches
their triggers. You can also ask for one directly:

```text
Use the web-to-PDF briefing workflow for this topic.
```

Prefer outcome-first requests:

```text
Create a sourced PDF briefing on this competitor and include risks.
```

OpenSquilla can then choose the matching workflow when one is available.

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

## Authoring

For full authoring rules, templates, safety notes, and examples, read:

```text
META_SKILL_GUIDE.md
```

Keep meta-skill descriptions user-facing. A good description tells users when to
use the workflow and what output to expect; it does not advertise scheduler
mechanics.

---

[Docs index](../README.md) · [Product guide](../../README.product.md) · [Improve this page](../contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)

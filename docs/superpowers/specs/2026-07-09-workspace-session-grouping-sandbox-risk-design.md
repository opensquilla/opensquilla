# Workspace Session Grouping and Codex-Like Sandbox Risk Design

Date: 2026-07-09

## Goals

OpenSquilla should feel closer to Codex when a user works from project directories:

- Sessions that belong to the same explicit workspace/project are grouped together in the left sidebar.
- Sessions without an opened project keep the current flat sidebar behavior.
- The active workspace is the default read/write boundary for sandboxed tools.
- Low-risk writes outside the workspace can be auto-approved when the user intent is clear.
- Sensitive or destructive operations remain blocked or require explicit approval.

## Non-Goals

- Do not redesign the sidebar visual system.
- Do not build a file explorer or directory tree.
- Do not change Windows or Linux sandbox behavior except through shared policy code where required.
- Do not remove approval handling entirely; only avoid unnecessary approval friction.

## Backend Session Contract

`sessions.list` should expose stable workspace metadata for each session row:

- `workspace`: the normalized explicit workspace path, or empty when no project workspace should be shown.
- `workspaceLabel`: the final path segment, such as `project1`.
- `workspaceDisplayPath`: the full path for tooltips and debugging.

The backend should not make the frontend infer this from raw `origin` data. It should resolve workspace metadata from saved sandbox run context when present, and otherwise treat the session as ungrouped. The default OpenSquilla workspace, such as `~/.opensquilla/workspace`, should be considered "no opened project" and remain ungrouped.

Forked or branched sessions should inherit the parent's workspace context so they stay under the same project group.

## Sidebar Behavior

The left sidebar keeps its current Recents surface and adds workspace grouping inside the Chats family only:

```text
project1
  session1
  session2
project2
  session3
session4
session5
```

Grouping rules:

- Sessions with the same `workspace` are grouped under one project header.
- The header label is `workspaceLabel`; the full path is available as a tooltip.
- Group headers are ordered by the most recent session in that group.
- Sessions inside a group keep recency ordering.
- Ungrouped sessions stay flat and keep current behavior.
- Existing subagent nesting still works under its parent session; workspace indentation is the outer grouping level.

## Workspace Sandbox Behavior

The workspace must be a first-class read/write boundary:

- Read and write operations inside the current workspace should be allowed without manual approval.
- File tools and shell tools should agree on workspace access.
- The macOS sandbox backend must not make workspace writes stricter than the shared OpenSquilla policy.

## Outside-Workspace Risk Behavior

Outside-workspace writes should use a Codex-like multi-factor review model instead of a single hard high-risk flag.

Risk features include:

- Whether the user explicitly requested the operation.
- Whether the target is a single ordinary file, a temporary probe, or a broad/batch operation.
- Whether the path is sensitive, protected metadata, a credential path, or a system path.
- Whether the operation is recoverable.
- Whether the current run mode has an approval surface.
- Whether the operation is read-only, write, delete, or destructive overwrite.

Expected policy:

- Workspace read/write: allow.
- Clear low-risk outside-workspace actions: auto-approve when policy allows.
- Medium-risk actions: use approval when an approval surface exists.
- Hard deny: system paths, credential paths, `.git`, `.codex`, protected metadata, broad destructive operations, and unsafe deletes.

## Testing

Backend tests:

- `sessions.list` returns workspace metadata for explicit project sessions.
- Default OpenSquilla workspace sessions remain ungrouped.
- Forked sessions inherit workspace metadata.
- Workspace read/write remains allowed.
- Low-risk outside-workspace operations can be auto-approved.
- Sensitive/protected paths are not auto-approved.

Frontend tests:

- `arrangeSidebarSections` groups sessions by workspace.
- Project headers use basename labels and preserve full paths.
- Ungrouped sessions remain flat.
- Recency ordering works for groups and group children.
- Existing subagent nesting is preserved.

Verification:

- Run focused backend sandbox/session tests.
- Run focused web UI unit tests.
- Run typecheck, lint, and the repository CI-equivalent suite where practical.

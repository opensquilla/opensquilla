# OpenSquilla server development guidance

## Repository role

This repository is the OpenSquilla application: Python runtime, Gateway, Web UI,
agent tools, citations, and the client side of the RAG Provider boundary. The
sibling `opensquilla-knowledge` repository owns ingestion, evidence storage, and
retrieval.

When running on `aliyun-ecs`, the only authoritative development checkout is:

```text
/mnt/data/opensquilla-dev/repos/opensquilla
```

Do not develop in `/root/Q3WORK`, `opensquilla-demo/**/releases`,
`opensquilla-e2e`, or any detached deployment checkout.

## Before changing code

1. Confirm the current directory is a normal Git checkout. On `aliyun-ecs`, it
   must be the authoritative development checkout or a task worktree below
   `/mnt/data/opensquilla-dev/worktrees/opensquilla/`.
2. Run `git status --short --branch` and preserve unrelated user changes.
3. Refuse to edit when HEAD is detached or the path is a deployment release.
4. Fetch `origin` and state the current branch and its upstream before writing.
5. For Knowledge-side changes, use the sibling repository rather than copying
   Knowledge implementation into OpenSquilla.

## Product boundary

- OpenSquilla generates answers; Knowledge returns Evidence only.
- Knowledge access goes through the published Provider contract. Do not import
  Knowledge internals or expose its database, projection, or embedding model in
  OpenSquilla domain types.
- Preserve Provider v1.1 compatibility, including capabilities negotiation,
  Search/Get semantics, effective retrieval-profile recording, source locators,
  Evidence/Citation persistence, and bounded source URLs.
- Customer uploads enter through the Gateway management proxy and Web UI. Do
  not let browser code hold the Knowledge management secret.
- Preview and g-fleet use different data/configuration. A code change must not
  silently point one environment at the other's Knowledge service.

## Generated and large files

- Never hand-edit `src/opensquilla/gateway/static/dist`; build the Web UI and
  refresh the bundle through the repository's established build flow.
- Never overwrite or commit hydrated router model files merely because Git LFS
  materialized them differently in a deployment checkout.
- Do not place caches, virtual environments, test databases, model downloads,
  or build scratch data in the repository.

## Verification

Use the smallest relevant checks first, then expand in proportion to risk.

```bash
python -m pytest <relevant test paths>
ruff check <changed Python paths>
ruff format --check <changed Python paths>
mypy <changed Python paths>
```

For Web UI changes:

```bash
cd opensquilla-webui
npm ci
npm run typecheck
npm run test:unit
npm run build
```

Provider/upload/citation changes must cover the corresponding Gateway, runtime,
RPC, persistence, contract-fixture, and frontend tests. Tests that require live
providers or paid APIs must remain opt-in.

## Git and deployment

- Push development branches to `git@github.com:opensquilla/opensquilla.git`.
- Do not force-push shared branches or push directly to `main` unless explicitly
  requested.
- A deployment must name an exact commit and be exported to a new immutable
  release directory. Never change HEAD inside a release whose name contains an
  older commit.
- Deployment switching is performed by an atomic `current` symlink plus health,
  Provider, UI-asset, and rollback checks. Source edits are never made in the
  live directory.

## Definition of done

A change is done only when the implementation, focused tests, static checks,
generated Web UI bundle when applicable, Git status review, and deployment
impact are all reported. State any real-service E2E or release gate that has not
been run.

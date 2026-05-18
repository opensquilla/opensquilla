## Checklist

- [ ] This pull request targets `dev`, unless a maintainer asked for a `main` release/hotfix/documentation PR.
- [ ] I ran `uv run ruff check src tests`.
- [ ] I ran `uv run pytest -q`.
- [ ] I ran `uv build --wheel`.
- [ ] Behavior changes include public regression tests.
- [ ] The default test path remains offline, deterministic, credential-free, and safe for forks.
- [ ] I did not commit secrets, local paths, private prompts, real provider transcripts, channel identifiers, or AI session artifacts.
- [ ] I did not commit maintainer-only files from `tests/_private/` or `.omx/private-golden/`.

## Live Checks

If this pull request changes provider, browser UI, gateway, or channel behavior, note whether a maintainer should run the `Live Release E2E` workflow.

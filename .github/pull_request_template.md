## Checklist

- [ ] This pull request targets `dev`, unless a maintainer asked for a `main` release/hotfix/documentation PR.
- [ ] I ran `uv run ruff check src tests`.
- [ ] I ran `uv run pytest -q`.
- [ ] I ran `uv build --wheel`.
- [ ] Behavior changes include public regression tests.
- [ ] The default test path remains offline, deterministic, credential-free, and safe for forks.
- [ ] I did not commit secrets, local paths, private prompts, real provider transcripts, channel identifiers, or AI session artifacts.
- [ ] I did not commit maintainer-only files from `tests/_private/` or `.omx/private-golden/`.
- [ ] Third-party origin is declared: `none`, `inspired-by`, `adapted/ported`, `vendored`, `direct dependency`, or `modified upstream`.
- [ ] For non-`none` third-party origin, I listed the upstream URL, license, whether code/rules/fixtures/text were copied or adapted, and updated notices/provenance where required.

## Live Checks

If this pull request changes provider, browser UI, gateway, or channel behavior, note whether a maintainer should run the `Live Release E2E` workflow.

## Documentation Changes

If this pull request changes documentation:

- [ ] Links point to existing repository files or stable external pages.
- [ ] Code fences and Markdown tables render correctly on GitHub.
- [ ] Examples avoid real secrets, local private paths, and private transcripts.
- [ ] User-facing feature pages explain when to use the feature, how to start, and where to troubleshoot next.

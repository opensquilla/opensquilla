# Code Review Dirty Repo Fixture

This fixture gives `meta-codereview-current-diff` a deterministic repository
shape. Test harnesses should copy this directory to a temporary git repository,
commit the baseline files, then apply `patch.diff` before invoking the
meta-skill.

Expected review concerns:

- The patch introduces a redacted credential placeholder.
- The patch removes input validation around `amount`.
- The patch changes behavior without adding or updating tests.

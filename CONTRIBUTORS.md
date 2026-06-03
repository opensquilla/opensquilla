# OpenSquilla Contributors

OpenSquilla uses GitHub pull requests, commits, release notes, and this
human-readable ledger together for contributor attribution. This file records
release-surface community work that can be harder to see when a release is
squash-merged or replayed onto `main`.

## OpenSquilla 0.3.1

The 0.3.1 release is prepared as a release-surface replay from `dev` onto the
stable `main` release ledger. Some community work in the release window was
already represented by earlier `main` attribution work; this section records
the 0.3.1-specific community contributions acknowledged in the release notes.

| Contributor | 0.3.1 contribution | Evidence |
| --- | --- | --- |
| [@openvictory](https://github.com/openvictory) | Visible running-state feedback plus short-drama and media helper workflows. | [#123](https://github.com/opensquilla/opensquilla/pull/123), [#133](https://github.com/opensquilla/opensquilla/pull/133), [#137](https://github.com/opensquilla/opensquilla/pull/137) |
| [@freeaccount-create](https://github.com/freeaccount-create) | Slack Socket Mode and self-targeting replies for channel workflows. | [#142](https://github.com/opensquilla/opensquilla/pull/142) |
| [@ruhook](https://github.com/ruhook) | Submitted the WebChat user-message newline preservation pull request. | [#124](https://github.com/opensquilla/opensquilla/pull/124) |
| [@qq712696307](https://github.com/qq712696307) | Authored the commit in #124 that preserved user-message newlines in WebChat. | [#124](https://github.com/opensquilla/opensquilla/pull/124) |
| [@Cola-Alex](https://github.com/Cola-Alex) | Increased tokenjuice summarize and failure-context windows for fallback tool-result projection. | [#143](https://github.com/opensquilla/opensquilla/pull/143) |
| [@nice-code-la](https://github.com/nice-code-la) | Voice workflow usability and clarification-pause resume behavior. | [#165](https://github.com/opensquilla/opensquilla/pull/165), [#166](https://github.com/opensquilla/opensquilla/pull/166) |

## OpenSquilla 0.3.0

The 0.3.0 release reached `main` through release synchronization after work had
landed through `dev` and integration branches. That compressed the default
branch commit history, so the following community contributions are recorded
explicitly here.

| Contributor | 0.3.0 contribution | Evidence |
| --- | --- | --- |
| [@ab2ence](https://github.com/ab2ence) | Tokenjuice tool-result compression and canonical projection, memory dream consolidation, chat streaming restore work, and cross-platform CI hardening. | [#56](https://github.com/opensquilla/opensquilla/pull/56), [#61](https://github.com/opensquilla/opensquilla/pull/61), [#81](https://github.com/opensquilla/opensquilla/pull/81), [#88](https://github.com/opensquilla/opensquilla/pull/88), [#109](https://github.com/opensquilla/opensquilla/pull/109) |
| [@lose4578](https://github.com/lose4578) | Submitted the TUI backend/runtime foundation pull request. | [#80](https://github.com/opensquilla/opensquilla/pull/80) |
| cwan0785 (commit author name; GitHub account: [@Anonymous-4427](https://github.com/Anonymous-4427)) | Authored the TUI backend/runtime extraction commits behind the foundation pull request. | [#80](https://github.com/opensquilla/opensquilla/pull/80) |
| [@nice-code-la](https://github.com/nice-code-la) | MetaSkill orchestration, router-control replay and hold behavior, retained high-value MetaSkill routing, lifestyle MetaSkill cleanup, and live MetaSkill execution hardening. | [#82](https://github.com/opensquilla/opensquilla/pull/82), [#93](https://github.com/opensquilla/opensquilla/pull/93), [#96](https://github.com/opensquilla/opensquilla/pull/96), [#110](https://github.com/opensquilla/opensquilla/pull/110), [#114](https://github.com/opensquilla/opensquilla/pull/114) replayed through [#115](https://github.com/opensquilla/opensquilla/pull/115), [#119](https://github.com/opensquilla/opensquilla/pull/119) |
| [@openvictory](https://github.com/openvictory) | UTF-8 migration loading fix for yoyo migrations on Windows locales, plus follow-up release-gate alignment. | [#116](https://github.com/opensquilla/opensquilla/pull/116) |

## Attribution Practice

When maintainer cleanup, replay, or squash merging collapses contributor
commits, the final non-empty commit should preserve each human contributor with
`Co-authored-by:` trailers that use GitHub-associated email addresses. Preserve
pull request author attribution and commit author attribution separately when
they differ.

# OpenSquilla Contributors

OpenSquilla uses GitHub pull requests, commits, release notes, and this
human-readable ledger together for contributor attribution. This file records
release-surface community work that can be harder to see when a release is
squash-merged or replayed onto `main`.

## OpenSquilla 0.4.0

The 0.4.0 release is prepared from current `dev` after `v0.3.1`. This section
records non-Open-Squilla contributor work with pull-request evidence in that
range. Some work was replayed or carried through Open-Squilla integration pull
requests; those rows name the original contributor and cite both the original
pull request and the integration pull request when useful.

| Contributor | 0.4.0 contribution | Evidence |
| --- | --- | --- |
| [@ab2ence](https://github.com/ab2ence) | Control UI migration and stabilization work, share-image export, Web Chat slash-input handling, bundled AwesomeWebpage MetaSkill work, the Coding mode toggle, and desktop gateway startup plus install telemetry hardening carried into `dev`. | [#264](https://github.com/opensquilla/opensquilla/pull/264), [#274](https://github.com/opensquilla/opensquilla/pull/274), [#177](https://github.com/opensquilla/opensquilla/pull/177), [#173](https://github.com/opensquilla/opensquilla/pull/173), [#313](https://github.com/opensquilla/opensquilla/pull/313), [#320](https://github.com/opensquilla/opensquilla/pull/320) |
| [@myz-ah](https://github.com/myz-ah) | Added the `code-task` workflow for isolated, runner-verified code changes behind Coding mode and improved Web UI LaTeX formula rendering. | [#311](https://github.com/opensquilla/opensquilla/pull/311), [#318](https://github.com/opensquilla/opensquilla/pull/318) |
| [@nice-code-la](https://github.com/nice-code-la) | Skills readiness in the Web UI, MetaSkill progress and clarification UX, manual-only `/meta` behavior, scoped MetaSkill run-history reads, router fallback/default refresh work, image follow-up routing gates, from-scratch `code-task` build support, and MetaSkill clarify resume feedback. | [#184](https://github.com/opensquilla/opensquilla/pull/184), [#222](https://github.com/opensquilla/opensquilla/pull/222), [#243](https://github.com/opensquilla/opensquilla/pull/243), [#253](https://github.com/opensquilla/opensquilla/pull/253), [#261](https://github.com/opensquilla/opensquilla/pull/261) carried through [#297](https://github.com/opensquilla/opensquilla/pull/297), [#272](https://github.com/opensquilla/opensquilla/pull/272), [#279](https://github.com/opensquilla/opensquilla/pull/279) carried through [#297](https://github.com/opensquilla/opensquilla/pull/297), [#321](https://github.com/opensquilla/opensquilla/pull/321), [#323](https://github.com/opensquilla/opensquilla/pull/323) |
| [@openvictory](https://github.com/openvictory) | MetaSkill run-history and rescue-action Control UI work carried through the session-contract Control UI integration. | [#264](https://github.com/opensquilla/opensquilla/pull/264) |
| [@weiconghe](https://github.com/weiconghe) | Preserved and replayed Gemini `thought_signature` metadata across provider tool-call turns. | [#312](https://github.com/opensquilla/opensquilla/pull/312) |
| [@changquanyou](https://github.com/changquanyou) | Accepted no-space SSE `data:` lines and improved managed-layer MetaSkill inspection. | [#214](https://github.com/opensquilla/opensquilla/pull/214) |
| [@nkgotcode](https://github.com/nkgotcode) | Fixed DOCX `skill_exec` export behavior. | [#262](https://github.com/opensquilla/opensquilla/pull/262) |
| [@C1-BA-B1-F3](https://github.com/C1-BA-B1-F3) | Made SSRF fake-IP DNS blocks actionable for operators. | [#298](https://github.com/opensquilla/opensquilla/pull/298) carried through [#309](https://github.com/opensquilla/opensquilla/pull/309) and [#310](https://github.com/opensquilla/opensquilla/pull/310) |
| [@BlueOcean223](https://github.com/BlueOcean223) | Reset TUI EOF state on cached reentry. | [#203](https://github.com/opensquilla/opensquilla/pull/203) |
| [@szdtzpj](https://github.com/szdtzpj) | Fixed environment test precedence and the TUI abort hook. | [#176](https://github.com/opensquilla/opensquilla/pull/176) |
| [@lose4578](https://github.com/lose4578) | Submitted the OpenTUI scrollback-native frontend work carried into the 0.4.0 preview backend. | [#182](https://github.com/opensquilla/opensquilla/pull/182) carried through [#277](https://github.com/opensquilla/opensquilla/pull/277) |
| cwan0785 (commit author name; GitHub account: [@Anonymous-4427](https://github.com/Anonymous-4427)) | Authored OpenTUI preview backend implementation commits carried into the 0.4.0 preview backend. | [#182](https://github.com/opensquilla/opensquilla/pull/182) carried through [#277](https://github.com/opensquilla/opensquilla/pull/277) |

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

# Remove Obsolete Approval Policy UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the misleading Web UI approval-policy selector and orphaned approvals page without changing inline approvals, sandbox gates, run modes, or backend compatibility APIs.

**Architecture:** Retire only Vue catalog/page code and assets that belong exclusively to the old global selector. Keep the `/approvals → /sessions` redirect plus all approval queue, REST, RPC, and sandbox behavior untouched.

**Tech Stack:** Vue 3, TypeScript, Vitest, Playwright, Vite, Python 3.12, pytest.

## Global Constraints

- Do not change `src/opensquilla/application`, `src/opensquilla/gateway/rpc_approvals.py`, `src/opensquilla/sandbox`, or approval HTTP/RPC scopes.
- Preserve `/approvals` redirect compatibility to `/sessions`.
- Preserve `ApprovalCard`, pending-approval badges/subscriptions, and `standard`/`trusted`/`full` run modes.
- Remove only locale keys, icons, comments, and generated assets exclusive to the retired UI.
- Rebuild the checked-in Web UI distribution after source changes.

---

### Task 1: Retire the Settings approval-policy destination

**Files:**
- Modify: `opensquilla-webui/src/composables/setup/useSettingsSection.test.ts`
- Modify: `opensquilla-webui/src/composables/setup/settingsSections.ts`
- Modify: `opensquilla-webui/src/components/settings/SettingsDialog.vue`
- Delete: `opensquilla-webui/src/components/settings/SettingsSafetyPanel.vue`
- Modify: `opensquilla-webui/e2e/settings-modal.spec.ts`

**Interfaces:**
- Consumes: `SETTINGS_SECTIONS`, `sectionFromRouteParam()`, and `isKnownSectionParam()`.
- Produces: no `safety` settings section; `/settings/safety` follows existing unknown-section fallback to `provider`.

- [ ] **Step 1: Write the failing contract test**

Add this case inside `describe('settings section IA', ...)`:

```ts
it('retires the obsolete approval-policy Safety section', () => {
  const ids = SETTINGS_SECTIONS.map(s => s.id)
  expect(ids).not.toContain('safety')
  expect(sectionFromRouteParam('safety')).toBe('provider')
  expect(isKnownSectionParam('safety')).toBe(false)
})
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd opensquilla-webui
npm run test:unit -- --run src/composables/setup/useSettingsSection.test.ts
```

Expected: the new assertion fails because `safety` remains canonical.

- [ ] **Step 3: Make the minimal settings deletion**

Remove the `safety` item and its explanatory comment from `SETTINGS_SECTIONS`. Remove the following from `SettingsDialog.vue`:

```vue
<SettingsSafetyPanel v-else-if="section === 'safety'" />
```

```ts
import SettingsSafetyPanel from '@/components/settings/SettingsSafetyPanel.vue'
```

Delete `SettingsSafetyPanel.vue`. In `settings-modal.spec.ts`, replace:

```ts
const CLIENT_SECTIONS = ['Safety', 'Appearance', 'Keyboard', 'Advanced']
```

with:

```ts
const CLIENT_SECTIONS = ['Appearance', 'Keyboard', 'Advanced']
```

and update its adjacent comment to remove Safety.

- [ ] **Step 4: Verify GREEN**

Run the command from Step 2. Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add opensquilla-webui/src/composables/setup/useSettingsSection.test.ts \
  opensquilla-webui/src/composables/setup/settingsSections.ts \
  opensquilla-webui/src/components/settings/SettingsDialog.vue \
  opensquilla-webui/src/components/settings/SettingsSafetyPanel.vue \
  opensquilla-webui/e2e/settings-modal.spec.ts
git commit -m "refactor(webui): retire approval policy settings"
```

### Task 2: Remove the orphan page and exclusive UI resources

**Files:**
- Modify: `opensquilla-webui/src/composables/setup/useSettingsSection.test.ts`
- Delete: `opensquilla-webui/src/views/ApprovalsView.vue`
- Modify: `opensquilla-webui/src/utils/icons.ts`
- Modify: `opensquilla-webui/src/locales/{en,de,es,fr,ja,zh-Hans}.json`
- Modify: `opensquilla-webui/src/router/sharedRoutes.ts`
- Modify: `opensquilla-webui/src/router/nav.test.ts`
- Modify: `opensquilla-webui/src/App.vue`
- Modify: `opensquilla-webui/src/stores/app.ts`
- Modify: `opensquilla-webui/src/composables/chat/useChatApprovals.ts`
- Modify: `opensquilla-webui/e2e/approval-card.spec.ts`

**Interfaces:**
- Consumes: old page-only locale namespace and `approvals` icon.
- Produces: no unreachable page/copy/icon while live approval event handling continues to use its current API.

- [ ] **Step 1: Write the failing locale-retirement test**

Add this case inside `describe('settings section IA', ...)`:

```ts
it('does not ship copy for retired approval-policy destinations', () => {
  expect(en.settings.rail).not.toHaveProperty('safety')
  expect(en.settings).not.toHaveProperty('safety')
  expect(en.console).not.toHaveProperty('approvals')
  expect(en.nav).not.toHaveProperty('approvals')
})
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd opensquilla-webui
npm run test:unit -- --run src/composables/setup/useSettingsSection.test.ts
```

Expected: the new test fails because all four English locale keys still exist.

- [ ] **Step 3: Delete only exclusive resources**

Delete `ApprovalsView.vue`. From every locale listed above remove these exact keys/objects:

```text
nav.approvals
settings.rail.safety
settings.safety
console.approvals
```

Remove `approvals` from both `IconName` and `ICONS` in `icons.ts`.

Remove comments that describe a live Approvals page or say the strategy moved to Settings → Safety. Rewrite them to describe the true preserved behavior: approvals are inline in chat, snapshot reconciliation observes decisions from another client, and the retired deep link redirects to Sessions. Do not change any executable approval behavior.

- [ ] **Step 4: Verify GREEN and absence**

Run:

```bash
cd opensquilla-webui
npm run test:unit -- --run src/composables/setup/useSettingsSection.test.ts src/router/nav.test.ts src/router/lastRoute.test.ts
npm run check:architecture
rg -n "ApprovalsView|SettingsSafetyPanel|settings\\.safety|rail\\.safety|console\\.approvals|nav\\.approvals|Settings → Safety" src e2e --glob '!**/static/**'
```

Expected: tests and architecture checks pass; `rg` returns no matches.

- [ ] **Step 5: Commit**

```bash
git add opensquilla-webui/src opensquilla-webui/e2e/approval-card.spec.ts
git commit -m "chore(webui): remove retired approvals surface"
```

### Task 3: Regenerate static assets and verify preserved contracts

**Files:**
- Modify through build: `src/opensquilla/gateway/static/dist/**`

**Interfaces:**
- Consumes: cleaned Web UI source.
- Produces: checked-in distribution with no Safety panel or standalone Approvals chunk.

- [ ] **Step 1: Run the full Web UI unit suite**

```bash
cd opensquilla-webui
npm run test:unit
```

Expected: all Vitest tests pass.

- [ ] **Step 2: Build the distribution**

```bash
cd opensquilla-webui
npm run build
```

Expected: architecture checks, Vue type checking, Vite build, dist normalization, and theme checks exit zero.

- [ ] **Step 3: Run focused browser and backend contracts**

```bash
cd opensquilla-webui
npm run test:e2e -- e2e/settings-modal.spec.ts e2e/approval-card.spec.ts
cd ..
.venv/bin/pytest -q \
  tests/test_application/test_approval_rpc.py \
  tests/test_gateway/test_rpc_approvals.py \
  tests/test_sandbox/test_run_modes.py \
  tests/test_tools/test_approval_unification.py
```

Expected: browser tests retain inline approvals without a Safety tab; selected backend tests pass without backend diffs.

- [ ] **Step 4: Inspect and commit generated assets**

```bash
git diff --check
git diff -- src/opensquilla/application src/opensquilla/gateway/rpc_approvals.py src/opensquilla/sandbox
git add src/opensquilla/gateway/static/dist
git commit -m "build(webui): refresh static assets"
```

Expected: no whitespace errors, no backend contract changes, and only regenerated distribution files are included.

### Task 4: Review, push, and open the pull request

**Files:**
- Review: all changed files from `origin/main...HEAD`.

**Interfaces:**
- Consumes: scoped source/docs/build commits.
- Produces: a branch pushed to `origin` and a PR targeting `main`.

- [ ] **Step 1: Review and verify branch state**

```bash
git status --short
git log --oneline origin/main..HEAD
git diff --check
```

Expected: a clean worktree and only scoped commits.

- [ ] **Step 2: Push and create PR**

```bash
git push -u origin fix/remove-obsolete-approval-policy-ui
gh pr create --base main --head fix/remove-obsolete-approval-policy-ui \
  --title "Remove obsolete approval policy UI" \
  --body "## Summary
- retire the non-authoritative Settings approval-policy selector
- remove the unreachable standalone approvals view and exclusive resources
- preserve inline approvals, run modes, and backend compatibility contracts

## Verification
- npm run test:unit
- npm run build
- npm run test:e2e -- e2e/settings-modal.spec.ts e2e/approval-card.spec.ts
- focused approval and run-mode pytest suites"
```

Expected: GitHub returns a PR URL targeting `main`.

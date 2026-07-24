import { expect, test, type Page } from '@playwright/test'

const CONTROL_URL = '/control/'
const SESSION_KEY = 'agent:main:webchat:e2e-assistant-activity'
const LIFECYCLE_SESSION_KEY = 'agent:main:webchat:e2e-assistant-activity-lifecycle'
const LIFECYCLE_TASK_ID = 'task-e2e-assistant-activity-lifecycle'

interface ActivityFixture {
  failed?: boolean
}

function wsResponse(id: string | number | undefined, payload: unknown) {
  return JSON.stringify({ type: 'res', id, ok: true, payload })
}

function wsEvent(event: string, payload: unknown) {
  return JSON.stringify({ type: 'event', event, payload })
}

async function mockActivityHistory(page: Page, fixture: ActivityFixture = {}) {
  await page.routeWebSocket(/\/ws$/, ws => {
    ws.onMessage(message => {
      let frame: Record<string, unknown>
      try {
        frame = JSON.parse(String(message)) as Record<string, unknown>
      } catch {
        return
      }
      if (frame.type !== 'req' || frame.id === undefined) return
      if (frame.method === 'connect') {
        ws.send(JSON.stringify({ protocol: 3, policy: {} }))
        return
      }
      if (frame.method === 'chat.history') {
        ws.send(JSON.stringify({
          type: 'res',
          id: frame.id,
          ok: true,
          payload: {
            messages: [{
              role: 'assistant',
              text: 'The canonical answer is complete.',
              id: `assistant-activity-${fixture.failed ? 'failed' : 'success'}`,
              timestamp: Math.floor(Date.now() / 1000) - 30,
              reasoning_content: 'I compared the available evidence before answering.',
              tool_calls: [{
                tool_use_id: 'activity-search',
                name: 'web_search',
                groupId: 'activity-group',
                input: { query: 'OpenSquilla activity' },
                result: fixture.failed ? 'Search service unavailable' : 'One verified result',
                is_error: fixture.failed === true,
                execution_status: { status: fixture.failed ? 'error' : 'success' },
              }],
              timeline: [
                { type: 'text', raw: 'Non-canonical streamed prefix.' },
                { type: 'tool-group', groupId: 'activity-group' },
                { type: 'text', raw: 'Non-canonical streamed suffix.' },
              ],
            }],
            has_more: false,
          },
        }))
        return
      }
      ws.send(JSON.stringify({ type: 'res', id: frame.id, ok: true, payload: {} }))
    })
    ws.send(JSON.stringify({ type: 'event', event: 'connect.challenge', payload: {} }))
  })
}

async function mockControlledActivityLifecycle(page: Page) {
  let sendFrame: ((frame: string) => void) | null = null
  let streamSeq = 3
  let settled = false

  const emit = (event: string, payload: Record<string, unknown>) => {
    if (!sendFrame) throw new Error('activity lifecycle websocket is not connected')
    sendFrame(wsEvent(event, {
      key: LIFECYCLE_SESSION_KEY,
      task_id: LIFECYCLE_TASK_ID,
      stream_seq: streamSeq++,
      ...payload,
    }))
  }

  await page.addInitScript(() => {
    window.localStorage.setItem('opensquilla-locale', 'en')
  })
  await page.route('**/api/approvals', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ pending: [] }),
  }))
  await page.routeWebSocket(/\/ws$/, ws => {
    sendFrame = frame => ws.send(frame)
    ws.send(wsEvent('connect.challenge', {}))
    ws.onMessage(message => {
      let frame: Record<string, unknown>
      try {
        frame = JSON.parse(String(message)) as Record<string, unknown>
      } catch {
        return
      }
      if (frame.type !== 'req') return
      const method = String(frame.method || '')
      if (method === 'connect') {
        ws.send(JSON.stringify({
          protocol: 3,
          policy: { tick_interval_ms: 30_000, webui_stream_idle_grace_ms: 1_260_000 },
        }))
        return
      }
      if (method === 'chat.send') {
        ws.send(wsResponse(frame.id as string | number | undefined, {
          accepted: true,
          session: LIFECYCLE_SESSION_KEY,
          sessionKey: LIFECYCLE_SESSION_KEY,
          task_id: LIFECYCLE_TASK_ID,
          stream_seq: 1,
        }))
        ws.send(wsEvent('task.running', {
          key: LIFECYCLE_SESSION_KEY,
          task_id: LIFECYCLE_TASK_ID,
          stream_seq: 1,
        }))
        ws.send(wsEvent('session.event.state_change', {
          key: LIFECYCLE_SESSION_KEY,
          task_id: LIFECYCLE_TASK_ID,
          stream_seq: 2,
          to_state: 'thinking',
        }))
        return
      }
      const messages = settled
        ? [{
            role: 'user',
            text: 'Inspect, draft, verify, and answer.',
            id: 'activity-lifecycle-user',
            message_id: 'activity-lifecycle-user',
            timestamp: Math.floor(Date.now() / 1000) - 30,
          }, {
            role: 'assistant',
            text: 'Final verified answer.',
            id: 'activity-lifecycle-assistant',
            message_id: 'activity-lifecycle-assistant',
            timestamp: Math.floor(Date.now() / 1000),
            tool_calls: [{
              tool_use_id: 'activity-inspect',
              name: 'read_file',
              groupId: 'activity-inspect-group',
              input: { path: '/private/project/chat.ts' },
              result: 'read',
              execution_status: { status: 'success' },
            }, {
              tool_use_id: 'activity-verify',
              name: 'bash_exec',
              groupId: 'activity-verify-group',
              input: { command: 'npm test' },
              result: 'verified',
              execution_status: { status: 'success' },
            }],
            timeline: [
              { type: 'tool-group', groupId: 'activity-inspect-group' },
              { type: 'text', raw: 'Draft candidate.' },
              { type: 'tool-group', groupId: 'activity-verify-group' },
              { type: 'text', raw: 'Final verified answer.' },
            ],
          }]
        : []
      const payloads: Record<string, unknown> = {
        'agents.list': { agents: [] },
        'chat.history': { messages, has_more: false, canonical_complete: true },
        'commands.list_for_surface': { commands: [] },
        'config.get': {
          squilla_router: { enabled: false, rollout_phase: 'observe', tiers: {} },
          permissions: {},
          skills: {},
        },
        'onboarding.status': { audioConfigured: false },
        'sessions.list': { sessions: [], has_more: false },
        'sessions.messages.subscribe': {
          subscribed: true,
          replay_complete: true,
          current_stream_seq: 0,
          run_status: 'idle',
        },
        'usage.status': { sessions: [] },
      }
      ws.send(wsResponse(
        frame.id as string | number | undefined,
        payloads[method] ?? {},
      ))
    })
  })

  return {
    emit,
    finish() {
      settled = true
      emit('session.event.done', {
        text: 'Final verified answer.',
        model: 'test/activity',
        input_tokens: 12,
        output_tokens: 4,
      })
    },
  }
}

test.describe('Completed assistant activity disclosure', () => {
  test('keeps the canonical answer visible and supports keyboard disclosure', async ({ page }) => {
    await mockActivityHistory(page)
    await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(SESSION_KEY))
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const activity = page.getByTestId('assistant-activity')
    await expect(activity).toBeVisible()
    await expect(activity).toHaveAttribute('data-share-expanded', 'false')
    await expect(activity).toContainText('Activity · 2 items')

    const answer = page.locator('.msg-ai-text')
    await expect(answer).toBeVisible()
    await expect(answer).toHaveText('The canonical answer is complete.')
    await expect(page.getByText('Non-canonical streamed prefix.')).toHaveCount(0)
    await expect(page.getByText('Non-canonical streamed suffix.')).toHaveCount(0)

    const row = activity.locator('.tool-row[data-op="web.search"]')
    await expect(row).toBeHidden()

    const summary = activity.locator('.assistant-activity__summary')
    const summaryArrow = summary.locator('.assistant-activity__summary-arrow')
    await expect(summaryArrow).toHaveCount(1)
    const idleSummaryStyles = await summary.evaluate((element) => {
      const summaryStyle = getComputedStyle(element)
      const arrow = element.querySelector<HTMLElement>('.assistant-activity__summary-arrow')
      return {
        backgroundColor: summaryStyle.backgroundColor,
        borderTopWidth: summaryStyle.borderTopWidth,
        boxShadow: summaryStyle.boxShadow,
        color: summaryStyle.color,
        arrowOpacity: arrow ? getComputedStyle(arrow).opacity : '',
      }
    })
    expect(idleSummaryStyles).toMatchObject({
      backgroundColor: 'rgba(0, 0, 0, 0)',
      borderTopWidth: '0px',
      boxShadow: 'none',
      arrowOpacity: '0',
    })
    await summary.hover()
    await expect(summaryArrow).toHaveCSS('opacity', '0.8')
    const hoverSummaryStyles = await summary.evaluate((element) => {
      const summaryStyle = getComputedStyle(element)
      const arrow = element.querySelector<HTMLElement>('.assistant-activity__summary-arrow')
      return {
        backgroundColor: summaryStyle.backgroundColor,
        boxShadow: summaryStyle.boxShadow,
        color: summaryStyle.color,
        arrowOpacity: arrow ? Number.parseFloat(getComputedStyle(arrow).opacity) : 0,
      }
    })
    expect(hoverSummaryStyles.backgroundColor).toBe('rgba(0, 0, 0, 0)')
    expect(hoverSummaryStyles.boxShadow).toBe('none')
    expect(hoverSummaryStyles.color).not.toBe(idleSummaryStyles.color)
    expect(hoverSummaryStyles.arrowOpacity).toBeGreaterThan(0)
    await summary.press('Enter')
    await expect(summary).toHaveAttribute('aria-expanded', 'true')
    await expect(activity).toHaveAttribute('data-share-expanded', 'true')
    await expect(row).toBeVisible()
    await expect(activity.locator('.thinking-block__body')).toContainText(
      'I compared the available evidence before answering.',
    )

    await row.click()
    await expect(row).toHaveAttribute('aria-expanded', 'true')
    const flatStyles = await activity.evaluate((element) => {
      const read = (selector: string) => {
        const target = element.querySelector<HTMLElement>(selector)
        if (!target) return null
        const style = getComputedStyle(target)
        return {
          backgroundColor: style.backgroundColor,
          borderTopWidth: style.borderTopWidth,
          boxShadow: style.boxShadow,
        }
      }
      return {
        card: read('.step-card'),
        section: read('.tool-row-section'),
      }
    })
    expect(flatStyles.card).toMatchObject({
      backgroundColor: 'rgba(0, 0, 0, 0)',
      borderTopWidth: '0px',
      boxShadow: 'none',
    })
    expect(flatStyles.section).toMatchObject({
      backgroundColor: 'rgba(0, 0, 0, 0)',
      borderTopWidth: '0px',
      boxShadow: 'none',
    })

    await summary.press('Space')
    await expect(summary).toHaveAttribute('aria-expanded', 'false')
    await expect(activity).toHaveAttribute('data-share-expanded', 'false')
    expect(await summary.evaluate(element => document.activeElement === element)).toBe(true)
    await expect(answer).toBeVisible()
  })

  test('keeps recovered failures collapsed and exposes the full error on demand', async ({ page }) => {
    await mockActivityHistory(page, { failed: true })
    await page.setViewportSize({ width: 320, height: 844 })
    await page.goto(CONTROL_URL + 'chat?session=' + encodeURIComponent(`${SESSION_KEY}-failed`))
    await page.waitForSelector('.conn-pill', { timeout: 10000 })

    const activity = page.getByTestId('assistant-activity')
    await expect(activity).toBeVisible()
    await expect(activity).toHaveAttribute('data-share-expanded', 'false')
    await expect(activity).toContainText('1 failure recovered')

    const errorRow = activity.locator('.tool-row--error')
    await expect(errorRow).toBeHidden()
    const summary = activity.locator('.assistant-activity__summary')
    await summary.press('Enter')
    await expect(activity).toHaveAttribute('data-share-expanded', 'true')
    await expect(errorRow).toBeVisible()
    await expect(errorRow).toHaveAttribute('aria-expanded', 'true')
    await expect(activity.locator('.tool-row-section--error')).toContainText(
      'Search service unavailable',
    )
    await expect(page.locator('.msg-ai-text')).toHaveText('The canonical answer is complete.')

    await activity.locator('.assistant-activity__label').evaluate((element) => {
      element.textContent = 'Sehr lange lokalisierte Aktivitätszusammenfassung'
    })
    const summaryOverflow = await summary.evaluate(element =>
      element.scrollWidth - element.clientWidth,
    )
    expect(summaryOverflow).toBeLessThanOrEqual(1)
    const pageOverflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(pageOverflow).toBeLessThanOrEqual(1)
  })
})

test.describe('Live assistant activity lifecycle', () => {
  test('moves draft text back into activity when a later tool starts, then settles', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    const lifecycle = await mockControlledActivityLifecycle(page)
    await page.goto(
      CONTROL_URL + 'chat?session=' + encodeURIComponent(LIFECYCLE_SESSION_KEY),
    )
    await expect(page.locator('.conn-pill.connected')).toBeVisible({ timeout: 10000 })

    await page.locator('.chat-textarea').fill('Inspect, draft, verify, and answer.')
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    const liveActivity = page.locator('.assistant-activity--live')
    await expect(liveActivity).toBeVisible()
    await expect(page.locator('.work-card')).toHaveCount(0)
    const liveStatus = liveActivity.locator('.assistant-activity__live-label')
    await expect(liveStatus).toHaveText('Working')
    await expect(liveStatus).toHaveAttribute('role', 'status')
    await expect(liveStatus).toHaveAttribute('aria-live', 'polite')
    await expect(liveStatus).toHaveAttribute('aria-atomic', 'true')
    await expect(liveActivity.getByText('Working', { exact: true })).toHaveCount(1)
    await expect(liveActivity.locator('[role="status"]')).toHaveCount(1)
    await expect(liveActivity.locator('.assistant-activity-status__row')).toHaveCount(0)
    const liveMotion = await liveActivity.evaluate((element) => ({
      dot: getComputedStyle(
        element.querySelector<HTMLElement>('.assistant-activity__live-dot')!,
      ).animationName,
      label: getComputedStyle(
        element.querySelector<HTMLElement>('.assistant-activity__live-label')!,
      ).animationName,
    }))
    expect(liveMotion.dot).not.toBe('none')
    expect(liveMotion.label).not.toBe('none')

    lifecycle.emit('session.event.tool_use_start', {
      tool_use_id: 'activity-inspect',
      name: 'read_file',
      input: { path: '/private/project/chat.ts' },
    })
    const inspectRow = liveActivity.locator('.tool-row[data-op="file.inspect"]')
    await expect(inspectRow).toBeVisible()
    await expect(inspectRow).toHaveAttribute('aria-expanded', 'false')
    await expect(liveActivity.locator('.step-chevron')).toHaveCount(0)
    await expect(liveActivity).not.toContainText('/private/project/chat.ts')
    await expect(liveStatus).toHaveText('Working')
    await expect(liveActivity.getByText('Inspected files', { exact: true })).toHaveCount(1)

    lifecycle.emit('session.event.tool_result', {
      tool_use_id: 'activity-inspect',
      name: 'read_file',
      input: { path: '/private/project/chat.ts' },
      result: 'read',
      execution_status: { status: 'success' },
    })
    lifecycle.emit('session.event.text_delta', { text: 'Draft candidate.' })

    const answerCandidate = page.locator('.live-answer-candidate')
    await expect(answerCandidate).toHaveText('Draft candidate.')
    await expect(liveActivity.getByText('Draft candidate.', { exact: true })).toHaveCount(0)
    await expect(liveStatus).toHaveText('Writing the answer')
    await expect(
      liveActivity.getByText('Writing the answer', { exact: true }),
    ).toHaveCount(1)
    await expect(liveActivity.locator('.assistant-activity-status__row')).toHaveCount(0)

    lifecycle.emit('session.event.tool_use_start', {
      tool_use_id: 'activity-verify',
      name: 'bash_exec',
      input: { command: 'npm test' },
    })
    await expect(answerCandidate).toHaveCount(0)
    await expect(liveActivity.getByText('Draft candidate.', { exact: true })).toBeVisible()
    await expect(liveActivity.locator('.tool-row[data-op="command.run"]')).toBeVisible()
    await expect(liveStatus).toHaveText('Working')
    await expect(liveActivity.getByText('Ran commands', { exact: true })).toHaveCount(1)

    lifecycle.emit('session.event.tool_result', {
      tool_use_id: 'activity-verify',
      name: 'bash_exec',
      input: { command: 'npm test' },
      result: 'verified',
      execution_status: { status: 'success' },
    })
    lifecycle.emit('session.event.text_delta', { text: 'Final verified answer.' })
    await expect(answerCandidate).toHaveText('Final verified answer.')
    await expect(liveActivity).toBeVisible()

    lifecycle.finish()
    await expect(liveActivity).toHaveCount(0)
    const settled = page.locator('.msg-ai .assistant-activity')
    await expect(settled).toBeVisible()
    await expect(settled).toHaveAttribute('data-share-expanded', 'false')
    const finalAnswer = page.locator('.msg-ai-text').filter({
      hasText: 'Final verified answer.',
    })
    await expect(finalAnswer).toBeVisible()
    expect(await settled.evaluate((element) =>
      element.contains(document.querySelector('.msg-ai-text')),
    )).toBe(false)
  })

  test('disables live activity motion when reduced motion is requested', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await mockControlledActivityLifecycle(page)
    await page.goto(
      CONTROL_URL + 'chat?session=' + encodeURIComponent(LIFECYCLE_SESSION_KEY),
    )
    await expect(page.locator('.conn-pill.connected')).toBeVisible({ timeout: 10000 })

    await page.locator('.chat-textarea').fill('Inspect, draft, verify, and answer.')
    await page.locator('.chat-send-btn[aria-label="Send"]').click()

    const liveActivity = page.locator('.assistant-activity--live')
    await expect(liveActivity).toBeVisible()
    const liveMotion = await liveActivity.evaluate((element) => ({
      dot: getComputedStyle(
        element.querySelector<HTMLElement>('.assistant-activity__live-dot')!,
      ).animationName,
      label: getComputedStyle(
        element.querySelector<HTMLElement>('.assistant-activity__live-label')!,
      ).animationName,
    }))
    expect(liveMotion).toEqual({ dot: 'none', label: 'none' })
  })
})

// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest'

const copySpy = vi.hoisted(() => vi.fn(async (_text: string) => undefined))
vi.mock('@/utils/browser', () => ({ copyTextWithFallback: copySpy }))

// The prefix deliberately carries `$$` and a trailing `$'` sequence: paths fed
// through String.replace would corrupt them unless the rewrite stays literal.
const PREFIX =
  "OPENSQUILLA_STATE_DIR='/tmp/a$$b/state' "
  + "OPENSQUILLA_GATEWAY_CONFIG_PATH='/tmp/x$' "
  + "'/apps/opensquilla-gateway'"

function setDesktopApi(api: unknown): void {
  ;(window as unknown as { opensquillaDesktop?: unknown }).opensquillaDesktop = api
}

interface StepInput {
  label: string
  command?: string
  detail?: string
}

async function mountSteps(steps: StepInput[], { desktop }: { desktop: boolean }) {
  vi.resetModules()
  copySpy.mockClear()
  document.body.innerHTML = ''
  setDesktopApi(desktop
    ? {
        getOsLocale: async () => 'en-US',
        isAutoUpdateEnabled: async () => false,
        getCliInvocation: async () => ({ mode: 'bundled', prefix: PREFIX }),
      }
    : undefined)
  const { createApp, h, nextTick } = await import('vue')
  const i18n = (await import('@/i18n')).default
  i18n.global.locale.value = 'en'
  const Component = (await import('./AdvancedCliSteps.vue')).default
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp({ render: () => h(Component, { steps, heading: 'Steps' }) })
  app.use(i18n)
  app.mount(el)
  await new Promise(resolve => setTimeout(resolve, 20))
  await nextTick()
  return el
}

describe('AdvancedCliSteps', () => {
  it('desktop: folds commands, rewrites the display, and copies the rewritten text literally', async () => {
    const el = await mountSteps(
      [{ label: 'Inspect channels', command: 'opensquilla channels status --json' }],
      { desktop: true },
    )

    const fold = el.querySelector('details.cli-fold')
    expect(fold).toBeTruthy()
    const code = fold!.querySelector('code')
    expect(code?.textContent).toBe(`${PREFIX} channels status --json`)

    ;(fold!.querySelector('button.health-step__copy') as HTMLButtonElement).click()
    await new Promise(resolve => setTimeout(resolve, 10))
    expect(copySpy).toHaveBeenCalledWith(`${PREFIX} channels status --json`)
  })

  it('desktop: keeps authored step numbers when guidance interleaves commands', async () => {
    const el = await mountSteps(
      [
        { label: 'Inspect channels', command: 'opensquilla channels status --json' },
        { label: 'Check credentials in the console' },
        { label: 'Restart gateway', command: 'opensquilla gateway restart' },
      ],
      { desktop: true },
    )

    const guidanceNumbers = Array.from(
      el.querySelectorAll('.health-steps > ol .health-step__number'),
    ).map(n => n.textContent)
    expect(guidanceNumbers).toEqual(['2'])

    const foldNumbers = Array.from(
      el.querySelectorAll('details.cli-fold .health-step__number'),
    ).map(n => n.textContent)
    expect(foldNumbers).toEqual(['1', '3'])
  })

  it('web: renders one flat list in authored order with unprefixed commands', async () => {
    const el = await mountSteps(
      [
        { label: 'Inspect channels', command: 'opensquilla channels status --json' },
        { label: 'Check credentials in the console' },
        { label: 'Restart gateway', command: 'opensquilla gateway restart' },
      ],
      { desktop: false },
    )

    expect(el.querySelector('details.cli-fold')).toBeNull()
    const rows = Array.from(el.querySelectorAll('.health-step'))
    expect(rows).toHaveLength(3)
    expect(rows.map(row => row.querySelector('.health-step__number')?.textContent))
      .toEqual(['1', '2', '3'])
    expect(rows[0].querySelector('code')?.textContent).toBe('opensquilla channels status --json')
    expect(rows[1].querySelector('code')).toBeNull()
    expect(rows[2].querySelector('code')?.textContent).toBe('opensquilla gateway restart')
  })
})

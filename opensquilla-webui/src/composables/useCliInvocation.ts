import { ref, type Ref } from 'vue'
import { usePlatform } from '@/platform'
import type { CliInvocation } from '@/platform'

// Matches the leading `opensquilla` CLI token only — `opensquilla gateway …`
// rewrites; `export FOO=…` and other shell lines pass through untouched.
const CLI_TOKEN = /^opensquilla(?=\s|$)/

const invocation: Ref<CliInvocation | null> = ref(null)
let loaded: Promise<void> | null = null

function ensureLoaded(): Promise<void> {
  if (!loaded) {
    loaded = (async () => {
      const platform = usePlatform()
      // Web installs are CLI-launched: the bare `opensquilla` token already
      // resolves in the operator's shell, so no rewrite is needed there.
      if (platform.capabilities.hasTerminalWorkflow) return
      invocation.value = (await platform.gateway.getCliInvocation?.()) ?? null
    })().catch(() => {
      invocation.value = null
    })
  }
  return loaded
}

/**
 * Rewrites copyable `opensquilla …` commands into invocations that actually
 * run on this machine. On desktop the CLI ships inside the app bundle (off
 * PATH) and the gateway reads its config/state roots from environment
 * variables, so the shell reports a paste-ready prefix carrying both. Any
 * failure to obtain the prefix degrades to the identity function.
 */
export function useCliInvocation() {
  void ensureLoaded()

  function format(command: string): string {
    const prefix = invocation.value?.prefix
    if (!prefix || !CLI_TOKEN.test(command)) return command
    // Function replacement keeps the prefix literal: paths inside it may
    // contain $-sequences that String.replace would otherwise expand.
    return command.replace(CLI_TOKEN, () => prefix)
  }

  return { format, invocation }
}

// Test-only: drop the module-level cache so specs can exercise fresh loads.
export function resetCliInvocationForTest() {
  invocation.value = null
  loaded = null
}

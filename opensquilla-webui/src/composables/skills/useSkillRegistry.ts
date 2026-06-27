import { ref, type Ref } from 'vue'
import type { useRpcStore } from '@/stores/rpc'
import { useToasts } from '@/composables/useToasts'
import type { RegistryResult } from '@/types/skills'

interface RegistrySearchData {
  results?: RegistryResult[]
}

interface InstallResult {
  success: boolean
  message?: string
  missing_still?: {
    bins?: string[]
    env?: string[]
  }
}

export interface SkillRegistry {
  registryQuery: Ref<string>
  githubUrl: Ref<string>
  registryResults: Ref<RegistryResult[]>
  registryLoading: Ref<boolean>
  installingId: Ref<string | null>
  installingDepsId: Ref<string | null>
  uninstallingName: Ref<string | null>
  searchRegistry: () => Promise<void>
  installGithub: () => void
  installSkill: (identifier: string, source: string) => Promise<void>
  installDeps: (name: string, installId: string) => Promise<boolean>
  uninstallSkill: (name: string) => Promise<boolean>
}

export function useSkillRegistry(
  rpc: ReturnType<typeof useRpcStore>,
  loadData: () => Promise<void>,
): SkillRegistry {
  const { pushToast } = useToasts()
  const registryQuery = ref('')
  const githubUrl = ref('')
  const registryResults = ref<RegistryResult[]>([])
  const registryLoading = ref(false)
  const installingId = ref<string | null>(null)
  const installingDepsId = ref<string | null>(null)
  const uninstallingName = ref<string | null>(null)

  async function searchRegistry() {
    if (!registryQuery.value.trim()) return
    registryLoading.value = true
    registryResults.value = []
    try {
      const data = await rpc.call<RegistrySearchData>('skills.search', { query: registryQuery.value.trim(), limit: 20 })
      registryResults.value = data.results || []
    } catch (err) {
      pushToast('Search failed: ' + (err as Error).message, { tone: 'danger' })
    } finally {
      registryLoading.value = false
    }
  }

  function installGithub() {
    const url = githubUrl.value.trim()
    if (!url) return
    void installSkill(url, 'github')
  }

  async function installSkill(identifier: string, source: string) {
    installingId.value = identifier
    try {
      const res = await rpc.call<InstallResult>('skills.install', { identifier, source })
      if (res.success) {
        await loadData()
      } else {
        pushToast(res.message || 'Install failed', { tone: 'danger' })
      }
    } catch (err) {
      pushToast((err as Error).message, { tone: 'danger' })
    } finally {
      installingId.value = null
    }
  }

  async function installDeps(name: string, installId: string): Promise<boolean> {
    if (!name || !installId) return false
    installingDepsId.value = installId
    try {
      const res = await rpc.call<InstallResult>('skills.deps.install', { name, install_id: installId })
      if (res.success) {
        pushToast(res.message || 'Installed', { tone: 'ok' })
        const still = res.missing_still || {}
        const stillMissing = (still.bins || []).length + (still.env || []).length
        await loadData()
        return stillMissing === 0
      }
      pushToast(res.message || 'Install failed', { tone: 'danger' })
      return false
    } catch (err) {
      pushToast((err as Error).message, { tone: 'danger' })
      return false
    } finally {
      installingDepsId.value = null
    }
  }

  async function uninstallSkill(name: string): Promise<boolean> {
    uninstallingName.value = name
    try {
      const res = await rpc.call<InstallResult>('skills.uninstall', { name })
      if (res.success) {
        await loadData()
        return true
      }
      pushToast(res.message || 'Uninstall failed', { tone: 'danger' })
      return false
    } catch (err) {
      pushToast((err as Error).message, { tone: 'danger' })
      return false
    } finally {
      uninstallingName.value = null
    }
  }

  return {
    registryQuery,
    githubUrl,
    registryResults,
    registryLoading,
    installingId,
    installingDepsId,
    uninstallingName,
    searchRegistry,
    installGithub,
    installSkill,
    installDeps,
    uninstallSkill,
  }
}

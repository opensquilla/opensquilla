import { ref, type Ref } from 'vue'
import type { useRpcStore } from '@/stores/rpc'
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
      console.warn('Search failed:', (err as Error).message)
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
        console.warn(res.message || 'Install failed')
      }
    } catch (err) {
      console.warn((err as Error).message)
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
        console.warn(res.message || 'Installed')
        const still = res.missing_still || {}
        const stillMissing = (still.bins || []).length + (still.env || []).length
        await loadData()
        return stillMissing === 0
      }
      console.warn(res.message || 'Install failed')
      return false
    } catch (err) {
      console.warn((err as Error).message)
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
      console.warn(res.message || 'Uninstall failed')
      return false
    } catch (err) {
      console.warn((err as Error).message)
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

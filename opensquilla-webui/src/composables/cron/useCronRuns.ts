import { ref, watch, type Ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import type { CronRun } from '@/types/cron'

export function useCronRuns(selectedId: Ref<string | null>) {
  const rpc = useRpcStore()
  const runs = ref<CronRun[]>([])
  const runsLoading = ref(false)

  async function loadRuns(jobId: string) {
    runsLoading.value = true
    try {
      const data = await rpc.call<{ runs?: CronRun[] } | CronRun[]>('cron.runs', { id: jobId, limit: 10 })
      runs.value = Array.isArray(data) ? data : (data.runs || [])
    } catch {
      runs.value = []
    } finally {
      runsLoading.value = false
    }
  }

  watch(selectedId, (id) => {
    if (id) loadRuns(id)
    else runs.value = []
  })

  return { runs, runsLoading, loadRuns }
}

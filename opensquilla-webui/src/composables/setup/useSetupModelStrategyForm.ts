import { computed, type ComputedRef } from 'vue'
import type { useSetupRouterForm } from '@/composables/setup/useSetupRouterForm'
import type { useSetupEnsembleForm } from '@/composables/setup/useSetupEnsembleForm'
import { staticB5ModeForProvider } from '@/composables/setup/useSetupEnsembleForm'

export type ModelStrategy = 'router' | 'ensemble' | 'single'

type RouterForm = ReturnType<typeof useSetupRouterForm>
type EnsembleForm = ReturnType<typeof useSetupEnsembleForm>
type ComputedValue<T> = T extends ComputedRef<infer Value> ? Value : never
type RouterPanel = ComputedValue<ReturnType<RouterForm['createPanel']>>
type EnsemblePanel = ComputedValue<ReturnType<EnsembleForm['createPanel']>>

interface ModelStrategyPanelContext {
  hasSavedProvider: ComputedRef<boolean>
  providerLabel: ComputedRef<string>
  routerPanel: ComputedRef<RouterPanel>
  ensemblePanel: ComputedRef<EnsemblePanel>
  routerTemplateState: ComputedRef<string>
}

export function useSetupModelStrategyForm(
  routerForm: RouterForm,
  ensembleForm: EnsembleForm,
  activeProvider?: ComputedRef<string>,
) {
  const activeStrategy = computed<ModelStrategy>(() => {
    if (ensembleForm.enabled.value) return 'ensemble'
    return routerForm.mode.value === 'disabled' ? 'single' : 'router'
  })

  const isDirty = computed(() => routerForm.isDirty.value || ensembleForm.isDirty.value)

  function setStrategy(next: ModelStrategy) {
    if (next === 'ensemble') {
      routerForm.setRouterMode('disabled')
      ensembleForm.setEnabled(true)
      ensembleForm.setSelectionMode(
        staticB5ModeForProvider(activeProvider?.value) ?? 'router_dynamic',
      )
      return
    }
    if (next === 'router') {
      ensembleForm.setEnabled(false)
      if (routerForm.mode.value === 'disabled' || routerForm.mode.value === 'openrouter-mix') {
        routerForm.setRouterMode('custom')
      }
      return
    }
    ensembleForm.setEnabled(false)
    routerForm.setRouterMode('disabled')
  }

  function createPanel(context: ModelStrategyPanelContext) {
    return computed(() => ({
      activeStrategy: activeStrategy.value,
      hasSavedProvider: context.hasSavedProvider.value,
      providerLabel: context.providerLabel.value,
      routerTemplateState: context.routerTemplateState.value,
      router: context.routerPanel.value,
      ensemble: context.ensemblePanel.value,
      cards: [
        {
          id: 'router' as const,
          enabled: activeStrategy.value === 'router',
          titleKey: 'setup.modelStrategy.cards.router.title',
          descKey: 'setup.modelStrategy.cards.router.desc',
        },
        {
          id: 'ensemble' as const,
          enabled: activeStrategy.value === 'ensemble',
          titleKey: 'setup.modelStrategy.cards.ensemble.title',
          descKey: 'setup.modelStrategy.cards.ensemble.desc',
        },
        {
          id: 'single' as const,
          enabled: activeStrategy.value === 'single',
          titleKey: 'setup.modelStrategy.cards.single.title',
          descKey: 'setup.modelStrategy.cards.single.desc',
        },
      ],
    }))
  }

  return {
    activeStrategy,
    isDirty,
    setStrategy,
    createPanel,
  }
}

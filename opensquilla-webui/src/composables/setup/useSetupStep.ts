import { ref } from 'vue'

export function useSetupStep(initialStep = 'provider') {
  const step = ref(initialStep)
  const hasAutoSelectedStep = ref(false)

  function setStep(newStep: string) {
    if (!newStep || newStep === step.value) return
    step.value = newStep
  }

  function markAutoSelected() {
    hasAutoSelectedStep.value = true
  }

  return {
    step,
    hasAutoSelectedStep,
    setStep,
    markAutoSelected,
  }
}

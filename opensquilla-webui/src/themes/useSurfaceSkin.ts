import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getManifest } from './registry'
import { ensureSkinAssets } from './apply'

// Axis-B resolver. The active expressive skin is derived from the current
// route's `meta.skin` — not stored — so navigation alone changes the surface
// and back/forward restore it for free. Returns the id + space-joined variant
// list for the content wrapper's `data-skin` / `data-skin-variant` attributes.
export function useSurfaceSkin() {
  const route = useRoute()

  const skinId = computed<string | undefined>(() => {
    const id = route.meta.skin
    if (!id) return undefined
    return getManifest(id)?.kind === 'expressive' ? id : undefined
  })

  const variants = computed<string>(() => {
    const id = skinId.value
    if (!id) return ''
    return (getManifest(id)?.skin?.variants ?? []).join(' ')
  })

  // Load the skin's lazy assets (fonts + scoped CSS + tokens) as soon as a
  // skinned route becomes active, before/while it paints.
  watch(
    skinId,
    (id) => {
      if (id) void ensureSkinAssets(id)
    },
    { immediate: true },
  )

  return { skinId, variants }
}

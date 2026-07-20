import { useI18n } from 'vue-i18n'

// The backend channel catalog ships label/description/whatYouNeed in English.
// This overlay localizes them by (type, field) key, falling back to the
// backend English whenever a key is absent — so a channel type or field the
// overlay has not translated yet degrades to English instead of breaking.
// Keys live under `setup.channelCatalog.<type>` and are covered for every
// catalog type by scripts/check-channel-catalog-i18n.mjs.
export function useChannelCatalogI18n() {
  const { t, te, tm } = useI18n()

  function tr(key: string, fallback: string): string {
    return te(key) ? t(key) : fallback
  }

  function localizeDescription(type: string, fallback?: string): string {
    return tr(`setup.channelCatalog.${type}.description`, fallback || '')
  }

  function localizeNeeds(type: string, fallback?: string[]): string[] {
    // `te` reports false for array messages, so probe the resolved value:
    // tm returns the localized array when present, else a non-array to fall back.
    const localized = tm(`setup.channelCatalog.${type}.needs`)
    if (Array.isArray(localized) && localized.length > 0 && localized.every(x => typeof x === 'string')) {
      return localized as string[]
    }
    return fallback || []
  }

  function localizeFieldLabel(type: string, name: string, fallback: string): string {
    return tr(`setup.channelCatalog.${type}.fields.${name}.label`, fallback)
  }

  // Group headers are shared vocabulary across channel types (credentials,
  // webhook, …): a per-type key wins when present, else the shared key, else
  // the caller's fallback (the humanized backend group name).
  function localizeGroupLabel(type: string, group: string, fallback: string): string {
    const typed = `setup.channelCatalog.${type}.groups.${group}`
    if (te(typed)) return t(typed)
    return tr(`setup.channelCatalog.groups.${group}`, fallback)
  }

  return { localizeDescription, localizeNeeds, localizeFieldLabel, localizeGroupLabel }
}

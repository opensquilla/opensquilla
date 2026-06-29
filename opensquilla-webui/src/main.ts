import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import i18n from './i18n'
import { useAppStore } from './stores/app'
import { useRpcStore } from './stores/rpc'
import 'katex/dist/katex.min.css'
import './assets/base.css'
import './styles/control-visual-system.css'
import './styles/route-fx.css'
import './styles/chat-markdown.css'
import './styles/chat-shared.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)

const appStore = useAppStore()
appStore.initTheme()

const rpcStore = useRpcStore()
rpcStore.init()

// Resolve + load the active locale before mounting so the first paint is
// already in the right language (no English flash). initLocale never rejects
// (it falls back to en internally); finally() guarantees the app still mounts.
appStore.initLocale().finally(() => {
  app.mount('#app')
})

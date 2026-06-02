import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { useAppStore } from './stores/app'
import { useRpcStore } from './stores/rpc'
import './assets/base.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)

const appStore = useAppStore()
appStore.initTheme()

const rpcStore = useRpcStore()
rpcStore.init()

app.mount('#app')

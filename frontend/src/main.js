import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/tailwind.css'
import { prodOriginUrl, shouldUseProdOrigin } from './utils/authRedirect'

function mountApp() {
  createApp(App).use(router).mount('#app')
}

if (typeof window !== 'undefined' && shouldUseProdOrigin(window.location.hostname)) {
  window.location.replace(prodOriginUrl(window.location.pathname, window.location.search, window.location.hash))
} else {
  mountApp()
}

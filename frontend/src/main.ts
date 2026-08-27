import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import HomeView from './views/HomeView.vue'
import './styles/tokens.css'
import './styles/base.css'
import './styles/markdown.css'
import 'katex/dist/katex.min.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: HomeView },
  ],
})

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')

// Hide loading overlay
const overlay = document.getElementById('loading-overlay')
if (overlay) {
  overlay.style.opacity = '0'
  overlay.style.transition = 'opacity 0.3s'
  setTimeout(() => overlay.remove(), 300)
}

import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from './views/DashboardView.vue'
import WizardView from './views/WizardView.vue'
import ReportView from './views/ReportView.vue'
import { initAuth } from './composables/useAuth'
import { trackRouteChange } from './lib/analytics'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/app' },
    { path: '/reports/demo', redirect: '/app' },
    { path: '/reports/demo/flow/:stepId', redirect: '/app' },
    { path: '/reports/demo/proof', redirect: '/app' },
    { path: '/reports/demo/fixes', redirect: '/app/blockers' },
    { path: '/demo-report', redirect: '/app' },
    {
      path: '/app',
      name: 'dashboard',
      component: DashboardView
    },
    {
      path: '/app/runs',
      name: 'runs',
      component: () => import('./views/RunsView.vue')
    },
    {
      path: '/app/blockers',
      name: 'blockers',
      component: () => import('./views/BlockersView.vue')
    },
    {
      path: '/app/analytics',
      name: 'analytics',
      component: () => import('./views/AnalyticsView.vue')
    },
    { path: '/app/fixes', redirect: '/app/blockers' },
    {
      path: '/app/new',
      name: 'new-audit',
      component: WizardView
    },
    {
      path: '/app/runs/:id/flow/:stepId',
      name: 'report-flow',
      component: ReportView,
      props: true
    },
    {
      path: '/app/runs/:id/fixes',
      redirect: (to) => ({ path: `/app/runs/${to.params.id}` })
    },
    {
      path: '/app/runs/:id/proof',
      name: 'report-proof',
      component: ReportView,
      props: true
    },
    {
      path: '/app/runs/:id',
      name: 'report',
      component: ReportView,
      props: true
    },
    {
      path: '/app/codex-runs/:id',
      redirect: (to) => ({ path: `/app/runs/${to.params.id}` })
    },
    { path: '/new', redirect: (to) => ({ path: '/app/new', query: to.query }) },
    { path: '/runs/:id', redirect: (to) => ({ path: `/app/runs/${to.params.id}` }) }
  ],
  scrollBehavior() {
    return { top: 0 }
  }
})

let authInitialized = false

router.beforeEach(async (to, _from, next) => {
  if (to.path === '/app/fixes' && typeof to.query.run === 'string' && to.query.run) {
    const { run, ...query } = to.query
    next({ path: `/app/runs/${run}`, query, hash: to.hash })
    return
  }

  if (!authInitialized) {
    authInitialized = true
    try {
      await initAuth()
    } catch (err) {
      console.error('auth init failed', err)
    }
  }

  next()
})

router.afterEach((to) => {
  trackRouteChange(to)
})

export default router

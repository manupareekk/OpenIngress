<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { initAuth, isAuthReady, useAuth } from '../composables/useAuth'
import { listRuns, runHasViewableReport } from '../api/ingress'
import DashboardShell from '../components/dashboard/DashboardShell.vue'
import TableCard from '../components/dashboard/TableCard.vue'
import { runSiteKey, siteOptionsFromRuns, sortRunsNewest } from '../utils/runSelectors'

const route = useRoute()
const router = useRouter()
const { refreshSession } = useAuth()

const runs = ref([])
const loading = ref(true)
const error = ref('')
let loadSeq = 0

const range = ref('30')
const query = ref('')
const siteKey = ref(typeof route.query.site === 'string' ? route.query.site : '')

const siteOptions = computed(() => siteOptionsFromRuns(runs.value))

watch(
  () => route.query.site,
  (v) => {
    siteKey.value = typeof v === 'string' ? v : ''
  }
)

watch(
  () => siteOptions.value,
  (opts) => {
    if (!opts.length || !siteKey.value) return
    if (opts.some((o) => o.key === siteKey.value)) return
    const nextQuery = { ...route.query }
    delete nextQuery.site
    router.replace({ path: route.path, query: nextQuery })
  },
  { immediate: true }
)

const loadRuns = async () => {
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    if (!isAuthReady()) {
      await initAuth()
    }
    runs.value = await listRuns()
    if (seq !== loadSeq) return
  } catch (e) {
    if (seq !== loadSeq) return
    error.value = e.response?.data?.error || e.message
    runs.value = []
  } finally {
    if (seq === loadSeq) {
      loading.value = false
    }
  }
}

onMounted(async () => {
  await refreshSession()
  await loadRuns()
})

onBeforeUnmount(() => {
  loadSeq += 1
})

const isActiveRun = (run) => run?.status === 'running' || run?.status === 'queued'

const sortedRuns = computed(() =>
  sortRunsNewest(runs.value)
)

const inRange = (run) => {
  const val = String(range.value || 'all')
  if (val === 'all') return true
  const days = Number(val)
  if (!Number.isFinite(days) || days <= 0) return true
  const ts = Date.parse(run?.created_at || '') || 0
  if (!ts) return true
  return ts >= Date.now() - days * 24 * 60 * 60 * 1000
}

const filteredRuns = computed(() => {
  const q = String(query.value || '').trim().toLowerCase()
  return sortedRuns.value
    .filter(inRange)
    .filter((run) => {
      if (!siteKey.value) return true
      return runSiteKey(run) === siteKey.value
    })
    .filter((run) => {
      if (!q) return true
      const hay = `${run.title || ''} ${run.url || ''} ${run.site_url || ''} ${run.run_id || ''}`.toLowerCase()
      return hay.includes(q)
    })
})

const openRun = (run) => {
  if (isActiveRun(run)) {
    router.push(`/app/runs/${run.run_id}`)
    return
  }
  if (runHasViewableReport(run)) {
    router.push(`/app/runs/${run.run_id}`)
    return
  }
  router.push({ path: '/app/new', query: { resume: run.run_id } })
}

const statusLabel = (status) => {
  if (status === 'completed') return 'Completed'
  if (status === 'queued') return 'Queued'
  if (status === 'running') return 'Running'
  if (status === 'failed') return 'Failed'
  return 'Draft'
}
</script>

<template>
  <DashboardShell title="Runs" :sites="siteOptions" :site-key="siteKey">
    <template #topbar>
      <div class="oi-dash-search">
        <span class="oi-dash-muted" aria-hidden="true">⌕</span>
        <input v-model="query" placeholder="Search runs…" />
      </div>
      <select v-model="range" class="oi-dash-select" aria-label="Date range">
        <option value="7">Last 7 days</option>
        <option value="30">Last 30 days</option>
        <option value="all">All time</option>
      </select>
      <router-link to="/app/new" class="oi-dash-btn oi-dash-btn-primary">New audit</router-link>
    </template>

    <div v-if="error" class="oi-dash-card oi-dash-card-pad" style="border-color:#b42318;color:#b42318;">
      {{ error }}
    </div>

    <TableCard title="All runs" subtitle="Every audit run, including drafts and in-progress runs.">
      <thead>
        <tr>
          <th style="text-align:left;">Run</th>
          <th style="text-align:left;">Status</th>
          <th style="text-align:left;">Score</th>
          <th style="text-align:left;">Loss</th>
          <th style="text-align:left;">Updated</th>
          <th style="text-align:left;">Action</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td colspan="6" class="oi-dash-muted">Loading runs…</td>
        </tr>
        <tr v-else-if="!filteredRuns.length">
          <td colspan="6" class="oi-dash-muted">No runs found.</td>
        </tr>
        <tr v-for="item in filteredRuns.slice(0, 50)" :key="item.run_id">
          <td>
            <button type="button" class="oi-dash-rowbtn" @click="openRun(item)">
              <div class="font-medium">{{ item.title || item.url || item.site_url || 'untitled run' }}</div>
              <div class="mt-xs oi-dash-muted">{{ item.run_id }}</div>
            </button>
          </td>
          <td>{{ statusLabel(item.status) }}</td>
          <td>
            <span v-if="item.overall_score != null">{{ Math.round(item.overall_score) }}</span>
            <span v-else-if="item.readiness_score != null">{{ Math.round(item.readiness_score) }}</span>
            <span v-else class="oi-dash-muted">—</span>
          </td>
          <td>
            <span v-if="item.actions_lost_percent != null">{{ Math.round(item.actions_lost_percent) }}%</span>
            <span v-else class="oi-dash-muted">—</span>
          </td>
          <td class="oi-dash-muted">{{ (item.updated_at || item.created_at || '').slice(0, 10) || '—' }}</td>
          <td>
            <button type="button" class="oi-dash-pill" @click="openRun(item)">
              {{ runHasViewableReport(item) ? 'View report' : isActiveRun(item) ? 'View progress' : item.status === 'failed' ? 'Retry' : 'Continue' }}
            </button>
          </td>
        </tr>
      </tbody>
    </TableCard>
  </DashboardShell>
</template>

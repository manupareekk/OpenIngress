<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { initAuth, isAuthReady, useAuth } from '../composables/useAuth'
import { getRun, listRuns } from '../api/ingress'
import DashboardShell from '../components/dashboard/DashboardShell.vue'
import Card from '../components/dashboard/Card.vue'
import TableCard from '../components/dashboard/TableCard.vue'
import {
  isActiveRun,
  latestFailedAfterUsable,
  latestUsableRun,
  runSiteKey,
  siteOptionsFromRuns,
  sortRunsNewest
} from '../utils/runSelectors'

const route = useRoute()
const router = useRouter()
const { refreshSession } = useAuth()

const runs = ref([])
const loading = ref(true)
const runLoading = ref(false)
const error = ref('')
const runPayload = ref(null)
let loadSeq = 0

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

const openRun = (run) => {
  if (isActiveRun(run)) {
    router.push(`/app/runs/${run.run_id}`)
    return
  }
  if (latestReportRun.value?.run_id === run?.run_id) {
    router.push(`/app/runs/${run.run_id}`)
    return
  }
  router.push({ path: '/app/new', query: { resume: run.run_id } })
}

function num(n) {
  const x = Number(n)
  return Number.isFinite(x) ? x : null
}

const siteRuns = computed(() =>
  sortRunsNewest(runs.value).filter((r) => {
    if (!siteKey.value) return true
    return runSiteKey(r) === siteKey.value
  })
)

const latestReportRun = computed(() => latestUsableRun(siteRuns.value))
const newerFailedRun = computed(() => latestFailedAfterUsable(siteRuns.value))

async function loadLatestPayload() {
  if (!latestReportRun.value?.run_id) {
    runPayload.value = null
    return
  }
  runLoading.value = true
  try {
    runPayload.value = await getRun(latestReportRun.value.run_id)
  } catch (e) {
    error.value = e.response?.data?.error || e.message
    runPayload.value = null
  } finally {
    runLoading.value = false
  }
}

watch(latestReportRun, () => {
  loadLatestPayload()
})

const blockerRows = computed(() => {
  const payload = runPayload.value || {}
  const exportsPayload = payload.exports || {}
  const agentReport = payload.agent_report || payload.audit?.agent_report || {}
  const rows = [
    ...(Array.isArray(exportsPayload.fixes) ? exportsPayload.fixes : []),
    ...(Array.isArray(agentReport.gaps) ? agentReport.gaps : []),
    ...(Array.isArray(agentReport.fixes) ? agentReport.fixes : [])
  ]
  for (const journey of exportsPayload.user_journeys || agentReport.job_results || []) {
    const status = String(journey?.status || '').toLowerCase()
    if (status === 'failed' || status === 'partial' || journey?.blocker) {
      rows.push({
        title: journey.job || journey.id || 'Agent job blocked',
        step: journey.job || journey.id || 'Agent job',
        detail: journey.blocker || journey.result || '',
        severity: status === 'failed' ? 'high' : 'medium'
      })
    }
  }
  const seen = new Set()
  const normalized = rows
    .map((item, index) => {
      const title = item.title || item.summary || item.text || item.gap || `Blocker ${index + 1}`
      const key = `${title}-${item.step || item.job || ''}-${item.severity || item.priority || ''}`
      if (seen.has(key)) return null
      seen.add(key)
      return {
        key,
        title,
        step: item.step || item.job || item.impact_area || 'Agent path',
        impact: item.detail || item.evidence || item.blocker || item.summary || item.text || '',
        severity: item.severity || item.priority || item.status || 'medium'
      }
    })
    .filter(Boolean)
  if (normalized.length) return normalized
  const run = latestReportRun.value
  if (!run || ((num(run.actions_lost_percent) ?? 0) <= 0 && (num(run.gap_count) ?? 0) <= 0)) return []
  return [
    {
      key: run.run_id,
      title: run.title || run.url || 'Latest audit blocker summary',
      step: 'Latest completed run',
      impact: `Loss ${run.actions_lost_percent == null ? '—' : `${Math.round(run.actions_lost_percent)}%`} · Gaps ${run.gap_count ?? '—'}`,
      severity: 'current'
    }
  ]
})

</script>

<template>
  <DashboardShell title="Blockers" :sites="siteOptions" :site-key="siteKey">
    <template #topbar>
      <router-link to="/app/new" class="oi-dash-btn oi-dash-btn-primary">New audit</router-link>
    </template>

    <div v-if="error" class="oi-dash-card oi-dash-card-pad" style="border-color:#b42318;color:#b42318;">
      {{ error }}
    </div>

    <div v-if="newerFailedRun" class="oi-dash-card oi-dash-card-pad oi-dash-muted">
      Latest audit failed on {{ (newerFailedRun.updated_at || newerFailedRun.created_at || '').slice(0, 10) || 'the last run' }}.
      Showing blockers from the latest completed report instead.
    </div>

    <Card
      title="Current blockers"
      :subtitle="latestReportRun ? `From latest completed run (${latestReportRun.run_id}).` : 'Run an audit to generate blockers.'"
    >
      <div class="flex flex-wrap gap-sm">
        <span class="oi-dash-pill">Run: {{ latestReportRun?.title || latestReportRun?.url || '—' }}</span>
        <span class="oi-dash-pill">Updated: {{ (latestReportRun?.updated_at || latestReportRun?.created_at || '').slice(0, 10) || '—' }}</span>
        <span class="oi-dash-pill" v-if="runLoading">Loading details…</span>
      </div>
    </Card>

    <TableCard title="Blockers" subtitle="Prioritized failure modes from the current report.">
      <thead>
        <tr>
          <th style="text-align:left;">Blocker</th>
          <th style="text-align:left;">Step</th>
          <th style="text-align:left;">Impact</th>
          <th style="text-align:left;">Severity</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading || runLoading">
          <td colspan="4" class="oi-dash-muted">Loading blockers…</td>
        </tr>
        <tr v-else-if="!blockerRows.length">
          <td colspan="4" class="oi-dash-muted">No blockers found in the latest completed run.</td>
        </tr>
        <tr v-for="item in blockerRows.slice(0, 25)" :key="item.key">
          <td>
            <button type="button" class="oi-dash-rowbtn" @click="openRun(latestReportRun)">
              <div class="font-medium">{{ item.title }}</div>
              <div class="mt-xs oi-dash-muted">{{ latestReportRun?.run_id }}</div>
            </button>
          </td>
          <td>{{ item.step }}</td>
          <td class="oi-dash-muted" style="max-width: 340px;">{{ item.impact || '—' }}</td>
          <td><span class="oi-dash-pill">{{ item.severity }}</span></td>
        </tr>
      </tbody>
    </TableCard>
  </DashboardShell>
</template>

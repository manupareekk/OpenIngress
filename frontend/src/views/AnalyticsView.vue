<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { initAuth, isAuthReady, useAuth } from '../composables/useAuth'
import { getRun, listRuns, runHasViewableReport } from '../api/ingress'
import DashboardShell from '../components/dashboard/DashboardShell.vue'
import StatCard from '../components/dashboard/StatCard.vue'
import Card from '../components/dashboard/Card.vue'
import TableCard from '../components/dashboard/TableCard.vue'
import { siteLabelFromKey } from '../utils/siteKey'
import {
  filterRunsByRange,
  latestFailedAfterUsable,
  latestUsableRun,
  mean,
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

const range = ref('30')
const selectedSite = ref('') // normalized key, '' means all sites
const siteSearch = ref('')

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

const inRange = (run) => {
  return filterRunsByRange([run], range.value).length > 0
}

const filteredRuns = computed(() => runs.value.filter(inRange))
const viewableRuns = computed(() => filteredRuns.value.filter((r) => runHasViewableReport(r)))

const siteOptions = computed(() => siteOptionsFromRuns(runs.value))

const isAllSites = computed(() => !selectedSite.value)

const siteScopedRuns = computed(() => {
  const key = selectedSite.value
  if (!key) return viewableRuns.value
  return viewableRuns.value.filter((r) => runSiteKey(r) === key)
})

const latestReportRun = computed(() => latestUsableRun(siteScopedRuns.value))
const newerFailedRun = computed(() => latestFailedAfterUsable(
  sortRunsNewest(filterRunsByRange(runs.value, range.value)).filter((r) => {
    if (!selectedSite.value) return true
    return runSiteKey(r) === selectedSite.value
  })
))

const totalRuns = computed(() => (isAllSites.value ? filteredRuns.value.length : siteScopedRuns.value.length))
const completedRuns = computed(() => (isAllSites.value ? filteredRuns.value : siteScopedRuns.value).filter((r) => r.status === 'completed').length)

const avgOverall = computed(() =>
  latestReportRun.value?.overall_score != null ? Number(latestReportRun.value.overall_score) : mean(siteScopedRuns.value.map((r) => (r.overall_score != null ? Number(r.overall_score) : null)))
)
const avgReadiness = computed(() =>
  latestReportRun.value?.readiness_score != null ? Number(latestReportRun.value.readiness_score) : mean(siteScopedRuns.value.map((r) => (r.readiness_score != null ? Number(r.readiness_score) : null)))
)
const avgA11y = computed(() =>
  latestReportRun.value?.agent_accessibility_score != null ? Number(latestReportRun.value.agent_accessibility_score) : mean(siteScopedRuns.value.map((r) => (r.agent_accessibility_score != null ? Number(r.agent_accessibility_score) : null)))
)
const avgSpeed = computed(() =>
  latestReportRun.value?.agent_speed_score != null ? Number(latestReportRun.value.agent_speed_score) : mean(siteScopedRuns.value.map((r) => (r.agent_speed_score != null ? Number(r.agent_speed_score) : null)))
)
const avgLoss = computed(() =>
  latestReportRun.value?.actions_lost_percent != null ? Number(latestReportRun.value.actions_lost_percent) : mean(siteScopedRuns.value.map((r) => (r.actions_lost_percent != null ? Number(r.actions_lost_percent) : null)))
)
const avgTimeLost = computed(() =>
  latestReportRun.value?.time_lost_percent != null ? Number(latestReportRun.value.time_lost_percent) : mean(siteScopedRuns.value.map((r) => (r.time_lost_percent != null ? Number(r.time_lost_percent) : null)))
)

const clampScore = (value) => Math.max(0, Math.min(100, Number(value) || 0))

const scoreTone = (value) => {
  if (value == null) return 'neutral'
  const score = clampScore(value)
  if (score >= 80) return 'good'
  if (score >= 55) return 'warn'
  return 'bad'
}

const lossTone = (value) => {
  if (value == null) return 'neutral'
  const loss = clampScore(value)
  if (loss <= 10) return 'good'
  if (loss <= 30) return 'warn'
  return 'bad'
}

const scoreDisplay = (value, suffix = '') => {
  if (value == null) return '—'
  return `${Math.round(clampScore(value))}${suffix}`
}

const completionEstimate = computed(() => {
  if (avgLoss.value == null) return null
  return Math.max(0, Math.min(100, 100 - avgLoss.value))
})

const scorePrimary = computed(() => avgOverall.value ?? completionEstimate.value ?? avgReadiness.value)

const scorePrimaryTone = computed(() => scoreTone(scorePrimary.value))

const scoreGaugeStyle = computed(() => {
  const score = clampScore(scorePrimary.value)
  const color =
    scorePrimaryTone.value === 'good'
      ? '#15803d'
      : scorePrimaryTone.value === 'warn'
        ? '#ca8a04'
        : scorePrimaryTone.value === 'bad'
          ? '#b42318'
          : '#888888'
  return {
    background: `conic-gradient(${color} ${score * 3.6}deg, #eeeeee 0deg)`
  }
})

const scoreHealthLabel = computed(() => {
  if (scorePrimary.value == null) return 'No score yet'
  const score = clampScore(scorePrimary.value)
  if (score >= 85) return 'Strong'
  if (score >= 70) return 'Watch list'
  if (score >= 50) return 'Needs work'
  return 'High risk'
})

const scoreMetrics = computed(() => [
  {
    label: 'Readiness',
    value: scoreDisplay(avgReadiness.value),
    width: `${clampScore(avgReadiness.value)}%`,
    tone: scoreTone(avgReadiness.value),
    note: 'Can agents complete intended work?'
  },
  {
    label: 'Accessibility',
    value: scoreDisplay(avgA11y.value),
    width: `${clampScore(avgA11y.value)}%`,
    tone: scoreTone(avgA11y.value),
    note: 'Can agents see the action surface?'
  },
  {
    label: 'Speed',
    value: scoreDisplay(avgSpeed.value),
    width: `${clampScore(avgSpeed.value)}%`,
    tone: scoreTone(avgSpeed.value),
    note: 'How expensive is the path to execute?'
  },
  {
    label: 'Action loss',
    value: scoreDisplay(avgLoss.value, '%'),
    width: `${clampScore(avgLoss.value)}%`,
    tone: lossTone(avgLoss.value),
    note: 'Lower is better.'
  },
  {
    label: 'Time lost',
    value: scoreDisplay(avgTimeLost.value, '%'),
    width: `${clampScore(avgTimeLost.value)}%`,
    tone: lossTone(avgTimeLost.value),
    note: 'Retries, dead ends, and wasted steps.'
  }
])

const topSites = computed(() => {
  const map = new Map()
  for (const r of viewableRuns.value) {
    const key = r.site_url || r.url || ''
    if (!key) continue
    map.set(key, (map.get(key) || 0) + 1)
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6)
})

const sortedSiteRuns = computed(() =>
  sortRunsNewest(siteScopedRuns.value)
)

const siteRunsFilteredBySearch = computed(() => {
  const q = String(siteSearch.value || '').trim().toLowerCase()
  if (!q) return sortedSiteRuns.value
  return sortedSiteRuns.value.filter((run) => {
    const hay = `${run.title || ''} ${run.url || ''} ${run.site_url || ''} ${run.run_id || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

const topBlockers = computed(() =>
  (latestReportRun.value ? [latestReportRun.value] : [])
    .filter((r) => (Number(r.actions_lost_percent) || 0) > 0 || (Number(r.gap_count) || 0) > 0)
    .slice(0, 5)
)

function statusLabel(status) {
  if (status === 'completed') return 'Completed'
  if (status === 'queued') return 'Queued'
  if (status === 'running') return 'Running'
  if (status === 'failed') return 'Failed'
  return 'Draft'
}

const syncFromRoute = () => {
  const qRange = typeof route.query.range === 'string' ? route.query.range : ''
  const qSite = typeof route.query.site === 'string' ? route.query.site : ''

  if (qRange) range.value = qRange
  selectedSite.value = qSite || ''
}

const syncToRoute = () => {
  const nextQuery = {
    ...route.query,
    range: range.value
  }
  if (selectedSite.value) nextQuery.site = selectedSite.value
  else delete nextQuery.site

  const cur = route.query || {}
  const same =
    String(cur.range || '') === String(nextQuery.range || '') &&
    String(cur.site || '') === String(nextQuery.site || '')

  if (same) return
  router.replace({ path: '/app/analytics', query: nextQuery })
}

watch(
  () => route.query,
  () => {
    syncFromRoute()
  }
)

watch([range], () => {
  syncToRoute()
})

watch(
  () => siteOptions.value,
  (opts) => {
    syncFromRoute()
    if (!opts.length || !selectedSite.value) return
    if (opts.some((o) => o.key === selectedSite.value)) return
    selectedSite.value = ''
    const nextQuery = { ...route.query, range: range.value }
    delete nextQuery.site
    router.replace({ path: route.path, query: nextQuery })
  },
  { immediate: true }
)

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

const buyerPathCoverage = computed(() => {
  const payload = runPayload.value || {}
  const journeys =
    payload.exports?.user_journeys ||
    payload.agent_report?.job_results ||
    payload.audit?.agent_report?.job_results ||
    []
  return (Array.isArray(journeys) ? journeys : []).map((step, index) => ({
    key: step.id || step.job || step.label || index,
    label: step.job || step.label || step.id || `Job ${index + 1}`,
    status: String(step.status || 'unknown').replace(/_/g, ' '),
    evidence: step.blocker || step.result || step.evidence || ''
  }))
})
</script>

<template>
  <DashboardShell title="Analytics" :sites="siteOptions" :site-key="selectedSite">
    <template #topbar>
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

    <div v-if="newerFailedRun" class="oi-dash-card oi-dash-card-pad oi-dash-muted">
      Latest audit failed on {{ (newerFailedRun.updated_at || newerFailedRun.created_at || '').slice(0, 10) || 'the last run' }}.
      Showing analytics from the latest completed report instead.
    </div>

    <div v-if="loading" class="oi-dash-card oi-dash-card-pad oi-dash-muted">Loading analytics…</div>

    <template v-else>
        <div class="oi-dash-grid cols-4">
          <StatCard label="Runs" :value="totalRuns" :hint="range === 'all' ? 'all time' : `last ${range}d`" />
          <StatCard label="Completed" :value="completedRuns" />
          <StatCard
            label="Completion est."
            :value="completionEstimate == null ? '—' : `${Math.round(completionEstimate)}%`"
          />
          <StatCard label="Latest overall" :value="avgOverall == null ? '—' : Math.round(avgOverall)" />
        </div>

        <div class="oi-dash-grid cols-2">
          <Card
            v-if="!isAllSites"
            title="Score breakdown"
            :subtitle="`Latest completed report for ${siteLabelFromKey(selectedSite)}.`"
          >
            <div class="oi-score-panel">
              <div class="oi-score-hero">
                <div class="oi-score-ring" :class="`is-${scorePrimaryTone}`" :style="scoreGaugeStyle">
                  <div>
                    <div class="oi-score-number">{{ scorePrimary == null ? '—' : Math.round(scorePrimary) }}</div>
                    <div class="oi-score-denom">/100</div>
                  </div>
                </div>
                <div class="min-w-0">
                  <div class="oi-score-status">{{ scoreHealthLabel }}</div>
                  <div class="oi-score-caption">
                    Current agent-readiness signal from the latest completed run.
                  </div>
                </div>
              </div>

              <div class="oi-score-bars">
                <div v-for="metric in scoreMetrics" :key="metric.label" class="oi-score-row">
                  <div class="oi-score-row-head">
                    <span>{{ metric.label }}</span>
                    <strong :class="`is-${metric.tone}`">{{ metric.value }}</strong>
                  </div>
                  <div class="oi-score-track" :class="`is-${metric.tone}`">
                    <span :style="{ width: metric.width }" />
                  </div>
                  <div class="oi-score-row-note">{{ metric.note }}</div>
                </div>
              </div>
            </div>
          </Card>

          <Card
            v-if="!isAllSites"
            title="Agent jobs"
            :subtitle="latestReportRun ? `Current jobs from ${latestReportRun.run_id}.` : 'No completed report yet.'"
          >
            <div v-if="runLoading" class="oi-dash-muted text-body-md">Loading jobs…</div>
            <div v-else-if="!buyerPathCoverage.length" class="oi-dash-muted text-body-md">No agent job data yet.</div>
            <div v-else class="flex flex-col gap-xs">
              <div v-for="step in buyerPathCoverage" :key="step.key" class="flex items-start justify-between gap-sm">
                <div class="min-w-0">
                  <div style="font-size: 13px; font-weight: 500;">{{ step.label }}</div>
                  <div class="oi-dash-muted truncate" style="font-size: 12px;">{{ step.evidence || 'No evidence text.' }}</div>
                </div>
                <span class="oi-dash-pill">{{ step.status }}</span>
              </div>
            </div>
          </Card>

          <Card v-else title="Most-audited sites" subtitle="Top sites in the selected time range.">
            <div v-if="!topSites.length" class="oi-dash-muted text-body-md">No sites yet.</div>
            <div v-else class="flex flex-col gap-xs">
              <div v-for="[site, n] in topSites" :key="site" class="flex items-center justify-between gap-sm">
                <div class="truncate" style="font-size: 13px;">{{ site }}</div>
                <span class="oi-dash-pill">{{ n }}</span>
              </div>
            </div>
          </Card>

          <Card
            v-if="!isAllSites"
            title="Top blockers"
            subtitle="Summary from the current completed run."
          >
            <div v-if="!topBlockers.length" class="oi-dash-muted text-body-md">No blockers found yet.</div>
            <div v-else class="flex flex-col gap-xs">
              <div
                v-for="r in topBlockers"
                :key="r.run_id"
                class="flex items-center justify-between gap-sm"
              >
                <div class="min-w-0">
                  <div class="truncate" style="font-size: 13px; font-weight: 500;">{{ r.title || 'Audit' }}</div>
                  <div class="oi-dash-muted truncate" style="font-size: 12px;">
                    Loss {{ r.actions_lost_percent == null ? '—' : `${Math.round(r.actions_lost_percent)}%` }}
                    <span v-if="r.gap_count != null"> · Gaps {{ r.gap_count }}</span>
                  </div>
                </div>
                <router-link
                  :to="`/app/runs/${r.run_id}`"
                  class="oi-dash-btn oi-dash-btn-ghost"
                  style="height: 32px;"
                >
                  Open
                </router-link>
              </div>
            </div>
          </Card>
        </div>

        <TableCard
          v-if="!isAllSites"
          title="Recent runs"
          :subtitle="`Runs for ${siteLabelFromKey(selectedSite)}.`"
        >
          <thead>
            <tr>
              <th style="text-align:left;">Run</th>
              <th style="text-align:left;">Status</th>
              <th style="text-align:left;">Overall</th>
              <th style="text-align:left;">Loss</th>
              <th style="text-align:left;">Gaps</th>
              <th style="text-align:left;">Updated</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colspan="6">
                <div class="oi-dash-search" style="width: min(420px, 100%);">
                  <span class="oi-dash-muted" aria-hidden="true">⌕</span>
                  <input v-model="siteSearch" placeholder="Search this site…" />
                </div>
              </td>
            </tr>
            <tr v-if="!siteRunsFilteredBySearch.length">
              <td colspan="6" class="oi-dash-muted">No runs found.</td>
            </tr>
            <tr v-for="r in siteRunsFilteredBySearch.slice(0, 20)" :key="r.run_id">
              <td>
                <router-link
                  :to="`/app/runs/${r.run_id}`"
                  class="oi-dash-rowbtn"
                  style="display:block;"
                >
                  <div class="font-medium">{{ r.title || r.run_id }}</div>
                  <div class="mt-xs oi-dash-muted">{{ r.run_id }}</div>
                </router-link>
              </td>
              <td>{{ statusLabel(r.status) }}</td>
              <td>
                <span v-if="r.overall_score != null">{{ Math.round(r.overall_score) }}</span>
                <span v-else-if="r.readiness_score != null">{{ Math.round(r.readiness_score) }}</span>
                <span v-else class="oi-dash-muted">—</span>
              </td>
              <td>
                <span v-if="r.actions_lost_percent != null">{{ Math.round(r.actions_lost_percent) }}%</span>
                <span v-else class="oi-dash-muted">—</span>
              </td>
              <td>
                <span v-if="r.gap_count != null">{{ r.gap_count }}</span>
                <span v-else class="oi-dash-muted">—</span>
              </td>
              <td class="oi-dash-muted">{{ (r.updated_at || r.created_at || '').slice(0, 10) || '—' }}</td>
            </tr>
          </tbody>
        </TableCard>
    </template>
  </DashboardShell>
</template>

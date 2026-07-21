<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getRun, listRuns, runHasViewableReport } from '../api/ingress'
import { initAuth, isAuthReady } from '../composables/useAuth'
import DashboardShell from '../components/dashboard/DashboardShell.vue'
import Card from '../components/dashboard/Card.vue'
import TableCard from '../components/dashboard/TableCard.vue'
import {
  filterRunsByRange,
  isActiveRun,
  latestFailedAfterUsable,
  latestUsableRun,
  runSiteKey,
  siteOptionsFromRuns,
  sortRunsNewest
} from '../utils/runSelectors'
import { siteLabelFromKey } from '../utils/siteKey'

const route = useRoute()
const router = useRouter()
const runs = ref([])
const loading = ref(true)
const error = ref('')
const runPayload = ref(null)
const runLoading = ref(false)
let loadSeq = 0
let runLoadSeq = 0

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
  await loadRuns()
})

onBeforeUnmount(() => {
  loadSeq += 1
  runLoadSeq += 1
})

const sortedRuns = computed(() =>
  sortRunsNewest(runs.value)
)

const openRun = (run) => {
  if (!run?.run_id) return
  if (isActiveRun(run)) {
    router.push(`/app/runs/${run.run_id}`)
    return
  }
  if (latestReportRun.value?.run_id === run.run_id || runHasViewableReport(run)) {
    router.push(`/app/runs/${run.run_id}`)
    return
  }
  router.push({ path: '/app/new', query: { resume: run.run_id } })
}

const runActionLabel = (run) => {
  if (isActiveRun(run)) return run.status === 'queued' ? 'Queued…' : 'Processing…'
  if (runHasViewableReport(run)) return 'View report'
  if (run.status === 'failed') return 'Retry'
  return 'Continue'
}

const statusLabel = (status) => {
  if (status === 'completed') return 'Completed'
  if (status === 'queued') return 'Queued'
  if (status === 'running') return 'Running'
  if (status === 'failed') return 'Failed'
  return 'Draft'
}

const testedDomain = (run) => siteLabelFromKey(runSiteKey(run)) || '—'

const query = ref('')
const range = ref('30')
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

const filteredRuns = computed(() => {
  const q = String(query.value || '').trim().toLowerCase()
  const base = filterRunsByRange(sortedRuns.value, range.value)
    .filter((run) => {
      if (!siteKey.value) return true
      return runSiteKey(run) === siteKey.value
    })
  if (!q) return base
  return base.filter((run) => {
    const hay = `${run.title || ''} ${run.url || ''} ${run.site_url || ''} ${run.run_id || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

const hasNoRuns = computed(() => !loading.value && !runs.value.length && !error.value)
const latestReportRun = computed(() => latestUsableRun(filteredRuns.value))
const newerFailedRun = computed(() => latestFailedAfterUsable(filteredRuns.value))
const selectedSiteLabel = computed(() => siteOptions.value.find((s) => s.key === siteKey.value)?.label || 'site')
const latestScore = computed(() => {
  const run = latestReportRun.value
  if (!run) return null
  if (run.overall_score != null) return Number(run.overall_score)
  if (run.readiness_score != null) return Number(run.readiness_score)
  return null
})
const latestLoss = computed(() =>
  latestReportRun.value?.actions_lost_percent == null ? null : Number(latestReportRun.value.actions_lost_percent)
)
const latestTimeLost = computed(() =>
  latestReportRun.value?.time_lost_percent == null ? null : Number(latestReportRun.value.time_lost_percent)
)
const latestA11y = computed(() =>
  latestReportRun.value?.agent_accessibility_score == null ? null : Number(latestReportRun.value.agent_accessibility_score)
)
const latestSpeed = computed(() =>
  latestReportRun.value?.agent_speed_score == null ? null : Number(latestReportRun.value.agent_speed_score)
)

const scoreTone = (value) => {
  if (value == null) return 'neutral'
  if (Number(value) >= 80) return 'good'
  if (Number(value) >= 60) return 'warn'
  return 'bad'
}

const lossTone = (value) => {
  if (value == null) return 'neutral'
  if (Number(value) <= 10) return 'good'
  if (Number(value) <= 30) return 'warn'
  return 'bad'
}

const signalMetrics = computed(() => [
  {
    label: 'Overall',
    value: latestScore.value == null ? '—' : Math.round(latestScore.value),
    note: 'run score',
    tone: scoreTone(latestScore.value)
  },
  {
    label: 'Access',
    value: latestA11y.value == null ? '—' : Math.round(latestA11y.value),
    note: 'agent-visible UI',
    tone: scoreTone(latestA11y.value)
  },
  {
    label: 'Speed',
    value: latestSpeed.value == null ? '—' : Math.round(latestSpeed.value),
    note: 'structure proxy',
    tone: scoreTone(latestSpeed.value)
  },
  {
    label: 'Loss',
    value: latestLoss.value == null ? '—' : `${Math.round(latestLoss.value)}%`,
    note: 'actions blocked',
    tone: lossTone(latestLoss.value)
  },
  {
    label: 'Time',
    value: latestTimeLost.value == null ? '—' : `${Math.round(latestTimeLost.value)}%`,
    note: 'lost to retries',
    tone: lossTone(latestTimeLost.value)
  },
  {
    label: 'Gaps',
    value: latestReportRun.value?.gap_count ?? '—',
    note: 'break points',
    tone: Number(latestReportRun.value?.gap_count || 0) > 0 ? 'warn' : 'good'
  }
])

const topBlockers = computed(() =>
  (latestReportRun.value ? [latestReportRun.value] : [])
    .filter((r) => (Number(r.actions_lost_percent) || 0) > 0 || (Number(r.gap_count) || 0) > 0)
)

const reportDate = computed(() => {
  const value = latestReportRun.value?.updated_at || latestReportRun.value?.created_at || ''
  return value ? value.slice(0, 10) : ''
})

const reportSummary = computed(() => [
  {
    label: 'Readiness',
    value: latestScore.value == null ? '—' : Math.round(latestScore.value),
    note: latestScore.value == null ? 'no score yet' : scoreTone(latestScore.value) === 'good' ? 'strong report' : 'needs review',
    tone: scoreTone(latestScore.value)
  },
  {
    label: 'Action loss',
    value: latestLoss.value == null ? '—' : `${Math.round(latestLoss.value)}%`,
    note: 'blocked or uncertain steps',
    tone: lossTone(latestLoss.value)
  },
  {
    label: 'Break points',
    value: latestReportRun.value?.gap_count ?? '—',
    note: 'where agents stall',
    tone: Number(latestReportRun.value?.gap_count || 0) > 0 ? 'warn' : 'good'
  }
])

const breakPointRows = computed(() => {
  const payload = runPayload.value
  if (!payload) return []
  const rows = []
  const seen = new Set()
  const push = (item, fallback) => {
    const title =
      item?.title || item?.summary || item?.label || item?.gap || item?.job || fallback
    if (!title) return
    const detail =
      item?.detail || item?.impact || item?.evidence || item?.blocker || item?.recommendation || ''
    const key = `${title}|${detail}`.slice(0, 180)
    if (seen.has(key)) return
    seen.add(key)
    rows.push({
      key,
      title,
      detail,
      severity: item?.severity || item?.priority || item?.status || 'medium'
    })
  }
  for (const item of payload.exports?.fixes || []) push(item, 'Fix')
  for (const item of payload.agent_report?.fixes || payload.audit?.agent_report?.fixes || []) {
    push(item, 'Fix')
  }
  for (const item of payload.agent_report?.gaps || payload.audit?.agent_report?.gaps || []) {
    push(item, 'Gap')
  }
  const journeys =
    payload.exports?.user_journeys ||
    payload.agent_report?.job_results ||
    payload.audit?.agent_report?.job_results ||
    []
  for (const journey of journeys) {
    const status = String(journey?.status || '').toLowerCase()
    if (status === 'failed' || status === 'partial' || journey?.blocker) {
      push(
        {
          title: journey.job || journey.id || 'Agent job blocked',
          detail: journey.blocker || journey.result || '',
          severity: status === 'failed' ? 'high' : 'medium'
        },
        'Agent job'
      )
    }
  }
  return rows
})

const blockersRoute = computed(() => ({
  path: '/app/blockers',
  query: siteKey.value ? { site: siteKey.value } : {}
}))

async function loadLatestRunPayload() {
  const runId = latestReportRun.value?.run_id
  if (!runId) {
    runPayload.value = null
    return
  }
  const seq = ++runLoadSeq
  runLoading.value = true
  try {
    const payload = await getRun(runId)
    if (seq === runLoadSeq) runPayload.value = payload
  } catch (e) {
    if (seq === runLoadSeq) runPayload.value = null
  } finally {
    if (seq === runLoadSeq) runLoading.value = false
  }
}

watch(latestReportRun, () => {
  loadLatestRunPayload()
})
</script>

<template>
  <DashboardShell title="Overview" :sites="siteOptions" :site-key="siteKey">
    <template #topbar>
      <div class="oi-dash-search">
        <span class="oi-dash-muted" aria-hidden="true">⌕</span>
        <input v-model="query" placeholder="Search audits…" />
      </div>
      <select v-model="range" class="oi-dash-select" aria-label="Date range">
        <option value="7">Last 7 days</option>
        <option value="30">Last 30 days</option>
        <option value="all">All time</option>
      </select>
      <router-link to="/app/new" class="oi-dash-btn oi-dash-btn-primary">New study</router-link>
    </template>

    <div v-if="error" class="oi-dash-card oi-dash-card-pad" style="border-color:#b42318;color:#b42318;">
      {{ error }}
    </div>

    <section v-else-if="hasNoRuns" class="oi-empty-dashboard">
      <div class="oi-empty-dashboard-hero">
        <p class="oi-empty-dashboard-kicker">No studies yet</p>
        <h1>Run your first site crawl.</h1>
        <p>
          Paste a URL. OpenIngress crawls the site with your LLM key and shows crawlability plus
          where agents break.
        </p>
        <div class="oi-empty-dashboard-actions">
          <router-link to="/app/new" class="oi-dash-btn oi-dash-btn-primary">Start first crawl</router-link>
        </div>
      </div>

      <div class="oi-empty-dashboard-grid">
        <article>
          <span>01</span>
          <h2>Crawl coverage</h2>
          <p>See which pages and actions the agent can reach from your site map.</p>
        </article>
        <article>
          <span>02</span>
          <h2>Break points</h2>
          <p>Find steps where navigation stalls, controls are missing, or flows fail.</p>
        </article>
        <article>
          <span>03</span>
          <h2>Evidence</h2>
          <p>Review agent jobs and break points from the latest completed study.</p>
        </article>
      </div>

      <div class="oi-empty-dashboard-preview">
        <div>
          <p class="oi-empty-dashboard-kicker">After your first run</p>
          <h2>Coverage and break map</h2>
          <p>Results appear here when a crawl finishes.</p>
        </div>
        <div class="oi-empty-funnel" aria-hidden="true">
          <span class="is-ok">Reach</span>
          <span class="is-warn">Operate</span>
          <span class="is-bad">Complete</span>
        </div>
      </div>
    </section>

    <template v-else>
    <div v-if="newerFailedRun" class="oi-dash-card oi-dash-card-pad oi-dash-muted">
      Latest audit failed on {{ (newerFailedRun.updated_at || newerFailedRun.created_at || '').slice(0, 10) || 'the last run' }}.
      Showing the latest completed report instead.
    </div>

    <div class="oi-dash-grid cols-2">
      <Card
        title="Latest report"
        :subtitle="latestReportRun ? `${selectedSiteLabel} · ${reportDate || latestReportRun.run_id}` : 'Run an audit to generate this site view.'"
      >
        <div v-if="loading" class="oi-dash-muted text-body-md">Loading latest report…</div>
        <div v-else-if="!latestReportRun" class="oi-dash-muted text-body-md">
          No completed report found for this site yet.
        </div>
        <div v-else class="oi-latest-report">
          <button type="button" class="oi-latest-report-main" @click="openRun(latestReportRun)">
            <div>
              <div class="oi-signal-label">Agent readiness</div>
              <div class="oi-latest-score">
                {{ latestScore == null ? '—' : Math.round(latestScore) }}<span>/100</span>
              </div>
              <div class="oi-signal-note">Latest completed report, not failed or in-progress runs.</div>
            </div>
            <span class="oi-dash-pill">Open report</span>
          </button>

          <div class="oi-signal-grid">
            <div
              v-for="metric in reportSummary"
              :key="metric.label"
              class="oi-signal-metric is-compact"
              :class="`is-${metric.tone}`"
            >
              <div class="oi-signal-label">{{ metric.label }}</div>
              <div class="oi-signal-value">{{ metric.value }}</div>
              <div class="oi-signal-note">{{ metric.note }}</div>
            </div>
          </div>
        </div>
      </Card>

      <Card
        title="Break points"
        :subtitle="latestReportRun ? 'Where the latest study stalled or failed.' : 'Break points appear after a completed study.'"
      >
        <div v-if="runLoading" class="oi-dash-muted text-body-md">Loading break points…</div>
        <div v-else-if="!latestReportRun" class="oi-dash-muted text-body-md">No completed report selected.</div>
        <div v-else-if="!breakPointRows.length" class="oi-blocker-snapshot is-empty">
          <div>
            <div class="oi-signal-label">No break points</div>
            <div class="mt-xs text-body-lg font-medium">Latest study looks clear.</div>
            <div class="mt-xs text-body-md oi-dash-muted">Re-run when the site changes.</div>
          </div>
        </div>
        <div v-else class="space-y-sm">
          <ul class="divide-y divide-[#eeeeee] border border-[#eeeeee] bg-white">
            <li
              v-for="item in breakPointRows.slice(0, 5)"
              :key="item.key"
              class="flex flex-col gap-xs px-md py-sm"
            >
              <div class="flex flex-wrap items-start justify-between gap-sm">
                <p class="text-body-md font-medium normal-case text-[#111111]">{{ item.title }}</p>
                <span class="oi-dash-pill">{{ item.severity }}</span>
              </div>
              <p v-if="item.detail" class="text-body-md normal-case leading-relaxed oi-dash-muted">
                {{ item.detail }}
              </p>
            </li>
          </ul>
          <div class="flex flex-wrap gap-sm">
            <router-link class="oi-dash-btn oi-dash-btn-primary" :to="blockersRoute">
              All break points
            </router-link>
            <button
              v-if="latestReportRun"
              type="button"
              class="oi-dash-btn oi-dash-btn-ghost"
              @click="openRun(latestReportRun)"
            >
              Open report
            </button>
          </div>
        </div>
      </Card>
    </div>

    <div class="oi-dash-grid cols-2">
      <Card title="Current report signals" subtitle="Supporting diagnostics from the latest report.">
        <div class="oi-signal-grid">
          <div
            v-for="metric in signalMetrics"
            :key="metric.label"
            class="oi-signal-metric"
            :class="`is-${metric.tone}`"
          >
            <div class="oi-signal-label">{{ metric.label }}</div>
            <div class="oi-signal-value">{{ metric.value }}</div>
            <div class="oi-signal-note">{{ metric.note }}</div>
          </div>
        </div>
      </Card>

      <Card title="Latest study" subtitle="Quick link back to the completed run.">
        <div v-if="topBlockers.length" class="flex flex-col gap-sm">
          <button
            v-for="run in topBlockers"
            :key="run.run_id"
            type="button"
            class="oi-blocker-snapshot"
            @click="openRun(run)"
          >
            <div class="min-w-0">
              <div class="oi-signal-label">Highest impact</div>
              <div class="mt-xs truncate text-body-lg font-medium">{{ run.title || run.url || 'Audit' }}</div>
              <div class="mt-xs text-body-md oi-dash-muted truncate">
                Latest completed report · {{ (run.updated_at || run.created_at || '').slice(0, 10) || run.run_id }}
              </div>
            </div>
            <div class="oi-blocker-stats">
              <div>
                <div class="oi-signal-value is-bad">{{ run.actions_lost_percent == null ? '—' : `${Math.round(run.actions_lost_percent)}%` }}</div>
                <div class="oi-signal-note">loss</div>
              </div>
              <div>
                <div class="oi-signal-value">{{ run.gap_count ?? '—' }}</div>
                <div class="oi-signal-note">gaps</div>
              </div>
              <span class="oi-dash-pill">Open report</span>
            </div>
          </button>
        </div>
        <div v-else class="oi-blocker-snapshot is-empty">
          <div>
            <div class="oi-signal-label">No active blockers</div>
            <div class="mt-xs text-body-lg font-medium">Latest report is clean</div>
            <div class="mt-xs text-body-md oi-dash-muted">Run another audit when the site changes.</div>
          </div>
        </div>
      </Card>
    </div>

    <TableCard
      title="Audits"
      :subtitle="siteKey ? `Recent runs for ${siteOptions.find((s) => s.key === siteKey)?.label || 'site'}.` : 'Recent runs across your sites.'"
    >
      <thead>
        <tr>
          <th style="text-align:left;">Audit</th>
          <th style="text-align:left;">Website</th>
          <th style="text-align:left;">Status</th>
          <th style="text-align:left;">Score</th>
          <th style="text-align:left;">Loss</th>
          <th style="text-align:left;">Gaps</th>
          <th style="text-align:left;">Action</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td colspan="7" class="oi-dash-muted">Loading audits…</td>
        </tr>
        <tr v-else-if="!filteredRuns.length">
          <td colspan="7" class="oi-dash-muted">No audits found.</td>
        </tr>
        <tr v-for="item in filteredRuns.slice(0, 12)" :key="item.run_id">
          <td>
            <button type="button" class="oi-dash-rowbtn" @click="openRun(item)">
              <div class="font-medium">{{ item.title || item.url || 'untitled audit' }}</div>
              <div class="mt-xs oi-dash-muted">{{ item.created_at?.slice(0, 10) || item.run_id }}</div>
            </button>
          </td>
          <td class="oi-dash-muted">{{ testedDomain(item) }}</td>
          <td>{{ statusLabel(item.status) }}</td>
          <td>
            <span v-if="item.overall_score != null">{{ Math.round(item.overall_score) }}</span>
            <span v-else-if="item.readiness_score != null">{{ Math.round(item.readiness_score) }}</span>
            <span v-else class="oi-dash-muted">—</span>
          </td>
          <td>
            <span v-if="item.actions_lost_percent != null">{{ item.actions_lost_percent }}%</span>
            <span v-else class="oi-dash-muted">—</span>
          </td>
          <td>
            <span v-if="item.gap_count != null">{{ item.gap_count }}</span>
            <span v-else class="oi-dash-muted">—</span>
          </td>
          <td>
            <button type="button" class="oi-dash-pill" @click="openRun(item)">
              {{ runActionLabel(item) }}
            </button>
          </td>
        </tr>
      </tbody>
    </TableCard>
    </template>
  </DashboardShell>
</template>

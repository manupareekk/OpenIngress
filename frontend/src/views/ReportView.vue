<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LoadingOverlay from '../components/layout/LoadingOverlay.vue'
import AgentReadinessReport from '../components/report/AgentReadinessReport.vue'
import DashboardShell from '../components/dashboard/DashboardShell.vue'
import {
  cancelRun,
  fetchRunAssetObjectUrl,
  getRun,
  pollRun,
  runHasViewableReport
} from '../api/ingress'
import { clearActiveAudit, saveActiveAudit } from '../utils/auditSession'
import { isLongRunningJobError, longRunningJobMessage } from '../utils/jobTimeout'
import { eventsToTraces } from '../utils/traces'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const notice = ref('')
const payload = ref(null)
const progress = ref('')
const rerunning = ref(false)
const busyPhase = ref('explore')
const progressPct = ref(0)
const activityLog = ref([])
const startedAt = ref('')
const screenshotObjectUrls = ref({})

let pollAbort = null
const loadingSections = ['Coverage', 'Agent jobs', 'Break points', 'Evidence']

const traces = computed(() => eventsToTraces(payload.value?.events || []))
const siteUrl = computed(
  () => payload.value?.draft?.siteUrl || payload.value?.draft?.beforeUrl || payload.value?.state?.site_url || ''
)
const title = computed(() => {
  try {
    return siteUrl.value ? new URL(siteUrl.value).hostname : 'Report'
  } catch {
    return 'Report'
  }
})

const proofPage = computed(() => route.name === 'report-proof')
const flowPage = computed(() => route.name === 'report-flow')
const subPage = computed(() => proofPage.value || flowPage.value)
const runPath = computed(() => `/app/runs/${route.params.id}`)
const flowStepId = computed(() => String(route.params.stepId || ''))

const sectionNavItem = (hash, label, key, icon) => {
  if (subPage.value) {
    return { to: { path: runPath.value, hash }, label, key, icon, exact: true }
  }
  return { hash, label, key, icon }
}

const flowRouteStepId = (row) =>
  String(row?.id || row?.job || row?.label || row?.index || 'step')
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '-')
    .replace(/^-+|-+$/g, '')

const flowRows = computed(() => {
  const journeys = payload.value?.exports?.user_journeys
  if (Array.isArray(journeys) && journeys.length) return journeys
  const jobs = payload.value?.agent_report?.job_results || payload.value?.audit?.agent_report?.job_results
  return Array.isArray(jobs) ? jobs : []
})

const flowNavItems = computed(() => {
  const rows = flowRows.value
  if (!rows.length) {
    return [
      { to: runPath.value, label: 'Agent jobs', key: 'agent-jobs', icon: 'runs', exact: true }
    ]
  }
  return rows.map((row) => ({
    to: `${runPath.value}/flow/${flowRouteStepId(row)}`,
    label: row.job || row.label || String(row.id || 'Agent job').replace(/_/g, ' '),
    key: `flow-${row.id || row.job || row.label}`,
    icon: row.status === 'success' || row.status === 'pass' ? 'overview' : 'blockers',
    exact: true
  }))
})

const runNavGroups = computed(() => [
  {
    label: title.value === 'Report' ? 'Current run' : title.value,
    items: [
      { to: { path: '/app/runs', preserveQuery: false }, label: 'All runs', key: 'all-runs', icon: 'runs', exact: true },
      sectionNavItem('#run-coverage', 'Coverage', 'run-coverage', 'overview'),
      sectionNavItem('#run-jobs', 'Agent jobs', 'run-jobs', 'runs'),
      sectionNavItem('#run-breakers', 'Break points', 'run-breakers', 'blockers')
    ]
  },
  {
    label: 'Agent jobs',
    items: flowNavItems.value
  },
  {
    label: 'Proof',
    items: [
      { to: `${runPath.value}/proof`, label: 'Agent proof', key: 'agent-proof', icon: 'runs', exact: true }
    ]
  }
])
const shellKey = computed(
  () =>
    `${title.value}:${flowNavItems.value.length}:${
      proofPage.value ? 'proof' : flowPage.value ? 'flow' : 'report'
    }`
)

const heroImage = computed(() => {
  for (const trace of traces.value) {
    for (const event of trace.events || []) {
      const shot = event.metadata?.screenshots?.viewport
      const objectUrl = screenshotObjectUrls.value[shot?.url]
      if (objectUrl) return objectUrl
    }
  }
  return ''
})

const screenshotUrls = (data) => {
  const urls = new Set()
  for (const event of data?.events || []) {
    for (const shot of Object.values(event.metadata?.screenshots || {})) {
      if (shot?.url) urls.add(shot.url)
    }
  }
  return Array.from(urls)
}

const revokeScreenshotObjectUrls = () => {
  for (const url of Object.values(screenshotObjectUrls.value)) {
    URL.revokeObjectURL(url)
  }
  screenshotObjectUrls.value = {}
}

const loadScreenshotObjectUrls = async (data) => {
  revokeScreenshotObjectUrls()
  const pairs = await Promise.all(
    screenshotUrls(data).map(async (url) => {
      try {
        return [url, await fetchRunAssetObjectUrl(url)]
      } catch {
        return [url, '']
      }
    })
  )
  screenshotObjectUrls.value = Object.fromEntries(pairs.filter(([, objectUrl]) => objectUrl))
}

const publishRunPayload = (data) => {
  payload.value = data
  loading.value = false
  if (proofPage.value) {
    loadScreenshotObjectUrls(data).catch(() => {})
  } else {
    revokeScreenshotObjectUrls()
  }
}

watch(proofPage, (isProofPage) => {
  if (!payload.value) return
  if (isProofPage) {
    loadScreenshotObjectUrls(payload.value).catch(() => {})
  } else {
    revokeScreenshotObjectUrls()
  }
})

const resetFlowScroll = () => {
  const scroller = document.querySelector('.oi-dash-content')
  if (scroller) scroller.scrollTop = 0
}

watch(
  () => route.fullPath,
  (path, prevPath) => {
    // Hash-only changes (Coverage / Agent jobs / Break points) must keep scroll
    // position from the sidebar anchor — resetting here yanked the page to top
    // while leaving the nav item highlighted.
    const pathOnly = String(path || '').split('#')[0]
    const prevOnly = String(prevPath || '').split('#')[0]
    if (pathOnly === prevOnly) return
    // Path changed with a section hash (e.g. leaving a job detail) — let the
    // shell scroll to that section instead of forcing top.
    if (String(path || '').includes('#')) return
    nextTick(resetFlowScroll)
    window.setTimeout(resetFlowScroll, 320)
  },
  { flush: 'sync' }
)

function applyRunState(data) {
  const state = data?.state || {}
  if (state.progress) progress.value = state.progress
  if (state.progress_pct != null) progressPct.value = state.progress_pct
  if (state.activity_log?.length) activityLog.value = state.activity_log
  if (state.started_at) startedAt.value = state.started_at
}

function newPollSignal() {
  pollAbort?.abort()
  pollAbort = new AbortController()
  return pollAbort.signal
}

const loadRun = async () => {
  let data = await getRun(route.params.id)
  const state = data.state || {}
  const isActive = state.status === 'running' || state.status === 'queued'
  if (isActive && runHasViewableReport(state, data)) {
    rerunning.value = false
    applyRunState(data)
    saveActiveAudit({ runId: route.params.id, siteUrl: siteUrl.value || state.site_url })
    notice.value = state.progress
      ? `Audit is still running: ${state.progress}. Showing the latest available report.`
      : 'Audit is still running. Showing the latest available report.'
    publishRunPayload(data)
    return
  }
  if (isActive) {
    rerunning.value = true
    busyPhase.value = state.job_phase === 'crawl' ? 'crawl' : 'explore'
    applyRunState(data)
    saveActiveAudit({ runId: route.params.id, siteUrl: siteUrl.value || state.site_url })
    try {
      data = await pollRun(route.params.id, {
        onTick: applyRunState,
        untilImport: state.job_phase === 'crawl',
        signal: newPollSignal()
      })
    } catch (e) {
      if (!isLongRunningJobError(e)) throw e
      notice.value = longRunningJobMessage(e)
      data = await pollRun(route.params.id, {
        intervalMs: 3000,
        maxWaitMs: 0,
        onTick: applyRunState,
        untilImport: data.state?.job_phase === 'crawl',
        signal: newPollSignal()
      })
    }
    clearActiveAudit()
    rerunning.value = false
  }
  if (data.state?.status === 'draft' && !runHasViewableReport(data.state, data)) {
    router.replace({ path: '/app/new', query: { resume: route.params.id } })
    return
  }
  publishRunPayload(data)
}

onBeforeUnmount(() => {
  pollAbort?.abort()
  revokeScreenshotObjectUrls()
})

onMounted(async () => {
  try {
    await loadRun()
  } catch (e) {
    if (e.message !== 'Audit cancelled') {
      if (isLongRunningJobError(e)) {
        notice.value = longRunningJobMessage(e)
      } else {
        error.value = e.response?.data?.error || e.message
      }
    }
  } finally {
    loading.value = false
    rerunning.value = false
  }
})

const stopRerun = async () => {
  progress.value = 'Stopping…'
  pollAbort?.abort()
  try {
    await cancelRun(route.params.id)
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  }
  clearActiveAudit()
  rerunning.value = false
  progress.value = ''
  try {
    loading.value = true
    await loadRun()
  } catch (e) {
    error.value = e.response?.data?.error || e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <DashboardShell :key="shellKey" :title="title" :nav-groups="runNavGroups">
    <template #topbar>
      <router-link to="/app" class="oi-dash-btn oi-dash-btn-ghost">Back</router-link>
      <router-link to="/app/new" class="oi-dash-btn oi-dash-btn-primary">New audit</router-link>
    </template>

    <div class="pb-xl px-gutter">
      <section
        v-if="loading && !rerunning"
        class="mx-auto max-w-[1120px] space-y-md"
        aria-live="polite"
      >
        <div class="oi-dash-card" style="overflow:hidden;">
          <div class="oi-dash-card-pad border-b" style="border-color: var(--oi-dash-border);">
            <div class="flex flex-wrap items-start justify-between gap-md">
              <div class="min-w-0">
                <p class="text-label-md normal-case oi-dash-muted">Report dashboard</p>
                <h1 class="mt-xs text-title-md font-medium normal-case text-[#111111]">
                  Preparing audit report
                </h1>
                <p class="mt-xs max-w-[680px] text-body-md normal-case leading-relaxed oi-dash-muted">
                  Fetching crawl coverage, agent job results, break points, and screenshots for this run.
                </p>
              </div>
              <span class="oi-dash-pill">{{ progress || 'Loading report…' }}</span>
            </div>
          </div>

          <div class="oi-dash-card-pad">
            <div class="oi-dash-grid cols-4">
              <article
                v-for="section in loadingSections"
                :key="section"
                class="oi-dash-card oi-dash-card-pad"
                style="background: var(--oi-dash-surface-2);"
              >
                <div class="text-label-md normal-case oi-dash-muted">{{ section }}</div>
                <div
                  class="mt-sm"
                  style="height: 14px; width: 62%; border-radius: 999px; background: linear-gradient(90deg, #eeeeee 25%, #fafafa 50%, #eeeeee 75%); background-size: 200% 100%; animation: dashboard-shimmer 1.2s ease-in-out infinite;"
                ></div>
                <div
                  class="mt-sm"
                  style="height: 10px; width: 86%; border-radius: 999px; background: linear-gradient(90deg, #eeeeee 25%, #fafafa 50%, #eeeeee 75%); background-size: 200% 100%; animation: dashboard-shimmer 1.2s ease-in-out infinite;"
                ></div>
                <div
                  class="mt-xs"
                  style="height: 10px; width: 48%; border-radius: 999px; background: linear-gradient(90deg, #eeeeee 25%, #fafafa 50%, #eeeeee 75%); background-size: 200% 100%; animation: dashboard-shimmer 1.2s ease-in-out infinite;"
                ></div>
              </article>
            </div>
          </div>
        </div>
      </section>

      <p v-if="notice" class="mx-auto mb-md max-w-[960px] border border-outline-variant px-sm py-xs text-body-md text-secondary">
        {{ notice }}
      </p>
      <p v-if="error" class="mx-auto mb-md max-w-[960px] border border-error px-sm py-xs text-body-md text-error">
        {{ error }}
      </p>

      <div v-if="payload && !loading && !rerunning" class="mx-auto max-w-[1120px]">
        <AgentReadinessReport
          :payload="payload"
          :traces="traces"
          :screenshot-object-urls="screenshotObjectUrls"
          :hero-image="heroImage"
          :proof-only="proofPage"
          :flow-only="flowPage"
          :flow-step-id="flowStepId"
          :run-path="runPath"
        />
      </div>
    </div>

    <LoadingOverlay
      :visible="rerunning"
      :message="progress"
      :phase="busyPhase"
      :progress-pct="progressPct"
      :activity-log="activityLog"
      :started-at="startedAt"
      :can-cancel="rerunning"
      @cancel="stopRerun"
    />
  </DashboardShell>
</template>

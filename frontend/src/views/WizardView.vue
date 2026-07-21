<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LoadingOverlay from '../components/layout/LoadingOverlay.vue'
import DashboardShell from '../components/dashboard/DashboardShell.vue'
import {
  cancelRun,
  createRun,
  exploreRun,
  explorePhaseDone,
  getRun,
  importPhaseDone,
  importSnapshot,
  pollRun,
  runHasViewableReport,
  validateSite
} from '../api/ingress'
import { clearActiveAudit, loadActiveAudit, saveActiveAudit } from '../utils/auditSession'
import { isLongRunningJobError } from '../utils/jobTimeout'
import { isValidSiteUrl, normalizeSiteUrl } from '../utils/normalizeSiteUrl'
import { trackEvent } from '../lib/analytics'

const router = useRouter()
const route = useRoute()
const busy = ref(false)
const busyMessage = ref('')
const busyPhase = ref('crawl')
const progressPct = ref(0)
const activityLog = ref([])
const startedAt = ref('')
const activeRunId = ref('')
const activeAuditKind = ref('standard')
const error = ref('')
const notice = ref('')
const showIntro = ref(false)
const siteValidation = ref(null)
const siteValidationLoading = ref(false)
const auditSubmitting = ref(false)
const auditPollMaxWaitMs = 6 * 60 * 1000

let pollAbort = null
let visibilityHandler = null
let validationSeq = 0

const form = reactive({
  title: 'Site audit',
  siteUrl: ''
})

const siteValidationRejected = computed(() => siteValidation.value && siteValidation.value.allowed === false)
const canSubmit = computed(() =>
  isValidSiteUrl(form.siteUrl) && !busy.value && !auditSubmitting.value && !siteValidationRejected.value
)
const siteHost = computed(() => {
  if (!form.siteUrl) return 'your site'
  try {
    return new URL(normalizeSiteUrl(form.siteUrl)).hostname.replace(/^www\./i, '')
  } catch {
    return form.siteUrl
  }
})
const longRunningNotice = computed(
  () => 'This is taking longer than usual — check Runs for progress.'
)
const loadingMessage = computed(() => {
  if (busyMessage.value) return busyMessage.value
  if (siteValidationLoading.value) return 'Checking site...'
  if (auditSubmitting.value) return 'Preparing study...'
  return ''
})
const isActiveRun = (state) => state?.status === 'running' || state?.status === 'queued'

watch(
  () => form.siteUrl,
  () => {
    validationSeq += 1
    siteValidation.value = null
    siteValidationLoading.value = false
  }
)

function applyRunState(data) {
  const state = data?.state || {}
  if (state.progress) busyMessage.value = state.progress
  if (state.progress_pct != null) progressPct.value = state.progress_pct
  if (state.activity_log?.length) activityLog.value = state.activity_log
  if (state.started_at) startedAt.value = state.started_at
  if (state.job_phase === 'explore') busyPhase.value = 'explore'
  else if (state.job_phase === 'crawl') busyPhase.value = 'crawl'
}

function setResumeQuery(runId) {
  if (route.query.resume === runId) return
  router.replace({ path: '/app/new', query: { resume: runId } })
}

function beginBusy(runId, siteUrl, kind = 'standard') {
  busy.value = true
  notice.value = ''
  activeRunId.value = runId
  saveActiveAudit({ runId, siteUrl, kind })
  setResumeQuery(runId)
}

function endBusy() {
  busy.value = false
  auditSubmitting.value = false
  busyMessage.value = ''
  activeRunId.value = ''
  activeAuditKind.value = 'standard'
  activityLog.value = []
  pollAbort?.abort()
  pollAbort = null
}

function newPollSignal() {
  pollAbort?.abort()
  pollAbort = new AbortController()
  return pollAbort.signal
}

async function validateSiteCandidate({ required = false } = {}) {
  const siteUrl = normalizeSiteUrl(form.siteUrl)
  if (!isValidSiteUrl(siteUrl)) {
    if (required) error.value = 'enter a domain like example.com or a full url.'
    return false
  }
  const current = siteValidation.value
  if (current?.url === siteUrl && current.allowed) return true
  if (current?.url === siteUrl && current.allowed === false) return false

  const seq = ++validationSeq
  siteValidationLoading.value = true
  try {
    const result = await validateSite(siteUrl)
    if (seq !== validationSeq) return false
    siteValidation.value = result
    if (result?.allowed && result.url && result.url !== siteUrl) {
      form.siteUrl = result.url.replace(/^https?:\/\//i, '')
    }
    return Boolean(result.allowed)
  } catch (e) {
    if (seq !== validationSeq) return false
    const validation = e.response?.data?.validation
    siteValidation.value =
      validation || {
        allowed: false,
        url: siteUrl,
        message: e.response?.data?.error || 'We could not confirm this site is crawlable.'
      }
    return false
  } finally {
    if (seq === validationSeq) siteValidationLoading.value = false
  }
}

async function pollImport(runId) {
  busyPhase.value = 'crawl'
  try {
    await pollRun(runId, {
      intervalMs: 1000,
      onTick: applyRunState,
      untilImport: true,
      signal: newPollSignal()
    })
  } catch (e) {
    if (!isLongRunningJobError(e)) throw e
    notice.value = longRunningNotice.value
    await pollRun(runId, {
      intervalMs: 3000,
      maxWaitMs: 0,
      onTick: applyRunState,
      untilImport: true,
      signal: newPollSignal()
    })
  }
}

async function pollExplore(runId) {
  busyPhase.value = 'explore'
  try {
    await pollRun(runId, {
      intervalMs: 1000,
      onTick: applyRunState,
      signal: newPollSignal()
    })
  } catch (e) {
    if (!isLongRunningJobError(e)) throw e
    notice.value = longRunningNotice.value
    await pollRun(runId, {
      intervalMs: 3000,
      maxWaitMs: 0,
      onTick: applyRunState,
      signal: newPollSignal()
    })
  }
}

async function startExplore(runId) {
  busyPhase.value = 'explore'
  busyMessage.value = 'starting agent…'
  const exploreResult = await exploreRun(runId)
  if (exploreResult.started === false) {
    throw new Error(exploreResult.message || 'Agent exploration could not start.')
  }
  await pollExplore(runId)
}

async function startImport(runId, siteUrl) {
  busyPhase.value = 'crawl'
  busyMessage.value = 'starting crawl…'
  progressPct.value = Math.max(progressPct.value, 5)
  const importResult = await importSnapshot(runId, 'before', siteUrl)
  if (importResult.started === false) {
    throw new Error(importResult.message || 'Crawl could not start.')
  }
  await pollImport(runId)
}

async function continueAudit(runId, siteUrl) {
  beginBusy(runId, siteUrl)
  error.value = ''
  notice.value = ''

  const data = await getRun(runId)
  applyRunState(data)
  const state = data.state || {}

  if (state.status === 'completed' || explorePhaseDone(state, data)) {
    clearActiveAudit()
    endBusy()
    await router.replace(`/app/runs/${runId}`)
    return
  }
  if (state.status === 'failed') {
    throw new Error(state.error || 'Audit failed')
  }

  if (isActiveRun(state) && state.job_phase === 'explore') {
    busyMessage.value = state.progress || 'agent exploring…'
    await pollExplore(runId)
  } else if (importPhaseDone(state)) {
    if (!explorePhaseDone(state, data)) {
      await startExplore(runId)
    }
  } else if (isActiveRun(state) && state.job_phase === 'crawl') {
    busyMessage.value = state.progress || 'crawling…'
    await pollImport(runId)
    await startExplore(runId)
  } else {
    await startImport(runId, siteUrl)
    await startExplore(runId)
  }

  clearActiveAudit()
  endBusy()
  await router.push(`/app/runs/${runId}`)
}

function hydrateFormFromRun(data) {
  form.title = data.state?.title || form.title
  form.siteUrl =
    data.draft?.siteUrl || data.draft?.beforeUrl || data.state?.site_url || form.siteUrl
}

async function tryResumeExistingRun() {
  const runId = String(route.query.resume || loadActiveAudit()?.runId || '')
  if (!runId) return

  activeRunId.value = runId
  setResumeQuery(runId)

  try {
    const data = await getRun(runId)
    hydrateFormFromRun(data)
    const state = data.state || {}
    const siteUrl =
      form.siteUrl ||
      data.draft?.siteUrl ||
      data.draft?.beforeUrl ||
      state.site_url ||
      loadActiveAudit()?.siteUrl ||
      ''

    if (isActiveRun(state)) {
      await continueAudit(runId, siteUrl)
      return
    }

    if (state.status === 'completed' || explorePhaseDone(state, data)) {
      clearActiveAudit()
      await router.replace(`/app/runs/${runId}`)
      return
    }

    if (state.status === 'failed' && runHasViewableReport(state, data)) {
      clearActiveAudit()
      await router.replace(`/app/runs/${runId}`)
      return
    }

    const inProgress =
      isActiveRun(state) ||
      (importPhaseDone(state) && !explorePhaseDone(state, data) && state.status !== 'failed')

    if (inProgress) {
      await continueAudit(runId, siteUrl)
      return
    }

    if (state.status === 'failed') {
      error.value = state.error || 'previous run failed.'
      clearActiveAudit()
    }
  } catch (e) {
    error.value = e.response?.data?.error || e.message
    endBusy()
  }
}

onMounted(async () => {
  const urlFromQuery = String(route.query.url || '').trim()
  if (urlFromQuery) {
    const normalized = normalizeSiteUrl(urlFromQuery)
    if (isValidSiteUrl(normalized)) {
      form.siteUrl = normalized
    }
  }
  const shouldAutostart = route.query.autostart === '1'
  showIntro.value = route.query.intro === '1' && isValidSiteUrl(form.siteUrl)

  visibilityHandler = () => {
    if (document.visibilityState === 'visible' && busy.value && activeRunId.value) {
      getRun(activeRunId.value)
        .then(applyRunState)
        .catch(() => {})
    }
  }
  document.addEventListener('visibilitychange', visibilityHandler)

  await tryResumeExistingRun()

  if (shouldAutostart && isValidSiteUrl(form.siteUrl) && !busy.value && !showIntro.value) {
    const query = { ...route.query }
    delete query.autostart
    await router.replace({ path: route.path, query })
    await runStandardAudit()
  }
})

onBeforeUnmount(() => {
  if (visibilityHandler) {
    document.removeEventListener('visibilitychange', visibilityHandler)
  }
  pollAbort?.abort()
})

const stopAudit = async () => {
  busyMessage.value = 'Stopping…'
  pollAbort?.abort()
  if (activeRunId.value) {
    try {
      await cancelRun(activeRunId.value)
    } catch (e) {
      error.value = e.response?.data?.error || e.message
    }
  }
  clearActiveAudit()
  endBusy()
}

const startIntroAudit = async () => {
  const query = { ...route.query }
  delete query.intro
  delete query.autostart
  await router.replace({ path: route.path, query })
  const started = await runStandardAudit()
  if (!started && !busy.value) showIntro.value = false
}

const editIntroUrl = async () => {
  showIntro.value = false
  const query = { ...route.query }
  delete query.intro
  delete query.autostart
  await router.replace({ path: route.path, query })
}

const runStandardAudit = async () => {
  if (auditSubmitting.value || busy.value) return false
  auditSubmitting.value = true
  busyPhase.value = 'crawl'
  const siteUrl = normalizeSiteUrl(form.siteUrl)
  if (!isValidSiteUrl(siteUrl)) {
    error.value = 'enter a domain like example.com or a full url.'
    auditSubmitting.value = false
    return false
  }
  if (!(await validateSiteCandidate({ required: true }))) {
    error.value = ''
    auditSubmitting.value = false
    return false
  }

  form.siteUrl = siteUrl
  error.value = ''
  notice.value = ''
  activityLog.value = []
  progressPct.value = 2
  startedAt.value = new Date().toISOString()
  activeAuditKind.value = 'standard'

  busy.value = true
  busyPhase.value = 'crawl'
  busyMessage.value = 'Starting crawl…'
  let runId = ''

  try {
    clearActiveAudit()
    trackEvent('audit_started')
    const created = await createRun({
      title: form.title || 'Site audit',
      siteUrl,
      beforeUrl: siteUrl
    })
    runId = created.run_id || created.state?.run_id
    if (!runId) throw new Error('Audit did not return a run id.')
    activeRunId.value = runId
    beginBusy(runId, siteUrl, 'standard')
    applyRunState({ state: created })
    await startImport(runId, siteUrl)
    await startExplore(runId)
    clearActiveAudit()
    endBusy()
    trackEvent('audit_completed')
    await router.push(`/app/runs/${runId}`)
    return true
  } catch (e) {
    if (e.message !== 'Audit cancelled') {
      if (isLongRunningJobError(e)) {
        notice.value = longRunningNotice.value
        await pollRun(runId, {
          intervalMs: 3000,
          maxWaitMs: 0,
          onTick: applyRunState,
          signal: newPollSignal()
        })
        clearActiveAudit()
        endBusy()
        trackEvent('audit_completed')
        await router.push(`/app/runs/${runId}`)
        return true
      } else {
        const detail = e.response?.data?.error || e.message
        error.value = detail
      }
    }
    clearActiveAudit()
    endBusy()
    return false
  }
}

</script>

<template>
  <DashboardShell title="New study">
    <template #topbar>
      <router-link to="/app" class="oi-dash-btn oi-dash-btn-ghost">Back</router-link>
    </template>

    <div class="pb-xl pt-md px-gutter">
      <div class="oi-home-stack">
        <section v-if="showIntro" class="oi-audit-intro-card">
          <div>
            <p class="oi-audit-intro-kicker">Self-hosted study</p>
            <h1>Ready to crawl your site?</h1>
            <p>
              OpenIngress crawls your pages with Playwright, then uses your LLM key to walk key
              flows and show where agents get stuck.
            </p>
          </div>

          <div class="oi-audit-intro-list" aria-label="What this study includes">
            <div><span>01</span><strong>Crawl coverage</strong></div>
            <div><span>02</span><strong>Where the agent broke</strong></div>
            <div><span>03</span><strong>Flow evidence</strong></div>
          </div>

          <div class="oi-audit-intro-safe">
            Read-only. No orders, payments, or site changes.
          </div>

          <div class="oi-audit-intro-store">
            <span>Site</span>
            <strong>{{ siteHost }}</strong>
          </div>

          <div class="oi-audit-intro-actions">
            <button type="button" class="oi-dash-btn oi-dash-btn-primary" @click="startIntroAudit">
              Start crawl
            </button>
            <button type="button" class="oi-dash-btn oi-dash-btn-secondary" @click="editIntroUrl">
              Edit URL
            </button>
          </div>

          <p class="oi-audit-intro-footnote">
            Requires <code>LLM_API_KEY</code> in <code>backend/.env</code>.
          </p>
        </section>

        <section v-else class="oi-home-intro">
          <p>New study</p>
          <p class="text-secondary">
            Paste a domain or URL. OpenIngress crawls the site and explores with your LLM key to
            report crawlability and break points.
          </p>
        </section>

        <p v-if="!showIntro && notice" class="border border-outline-variant px-sm py-xs text-body-md text-secondary">{{ notice }}</p>
        <p v-if="!showIntro && error" class="border border-error px-sm py-xs text-body-md text-error">{{ error }}</p>

        <section v-if="!showIntro" class="flex flex-col gap-sm">
          <form class="flex flex-col gap-md" @submit.prevent="runStandardAudit">
            <div class="flex flex-col gap-xs">
              <label class="text-body-md text-secondary" for="site-url">Site URL</label>
              <input
                id="site-url"
                v-model="form.siteUrl"
                class="oi-input-underline normal-case"
                placeholder="example.com"
                type="text"
                inputmode="url"
                autocomplete="url"
                spellcheck="false"
                required
                @blur="validateSiteCandidate()"
              />
              <p v-if="siteValidationLoading" class="text-label-md text-secondary">
                Checking site…
              </p>
              <div v-else-if="siteValidationRejected" class="oi-site-validation-reject">
                <p>{{ siteValidation.message }}</p>
              </div>
            </div>

            <div class="flex flex-col gap-xs">
              <label class="text-body-md text-secondary" for="audit-name">Study name</label>
              <input
                id="audit-name"
                v-model="form.title"
                class="oi-input-underline normal-case"
                placeholder="Homepage regression"
                type="text"
              />
            </div>

            <div class="flex flex-col gap-xs sm:flex-row">
              <button
                type="submit"
                class="oi-price-btn w-full sm:w-auto"
                :disabled="!canSubmit"
                @pointerdown.prevent="runStandardAudit"
              >
                Run Agent Audit
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>

    <LoadingOverlay
      :visible="busy || auditSubmitting"
      :message="loadingMessage"
      :notice="notice"
      :loading-insights="[]"
      :phase="busyPhase"
      :progress-pct="progressPct"
      :activity-log="activityLog"
      :started-at="startedAt"
      :can-cancel="busy"
      @cancel="stopAudit"
    />
  </DashboardShell>
</template>

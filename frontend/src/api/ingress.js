import { api, apiBaseURL } from '../lib/apiClient'

export const JOB_LONGER_THAN_EXPECTED_MESSAGE =
  'This is taking longer than usual — check Runs for progress.'

export class JobLongerThanExpectedError extends Error {
  constructor(message = JOB_LONGER_THAN_EXPECTED_MESSAGE) {
    super(message)
    this.name = 'JobLongerThanExpectedError'
    this.isLongRunningJob = true
  }
}

export const getLlmStatus = () => api.get('/config/llm').then((r) => r.data)
export const getAccount = () => api.get('/account/me').then((r) => r.data)
export const validateSite = (url) => api.post('/site-validation', { url }).then((r) => r.data)
/** @deprecated Prefer validateSite */
export const validateStorefront = validateSite
export const listRuns = () => api.get('/runs').then((r) => r.data.runs)
export const createRun = (payload) => api.post('/runs', payload).then((r) => r.data)
export const getRun = (id) => api.get(`/runs/${id}`).then((r) => r.data)
export const getTeaserCheck = (id) => api.get(`/runs/${id}/check`).then((r) => r.data)
export const cancelRun = (id) => api.post(`/runs/${id}/cancel`).then((r) => r.data)
/** Starts crawl in background; returns immediately — do not use a long client timeout. */
export const importSnapshot = (id, phase, url) =>
  api.post(`/runs/${id}/import`, { phase, url }).then((r) => r.data)
export const executeRun = (id) => api.post(`/runs/${id}/execute`).then((r) => r.data)
export const exploreRun = (id) => api.post(`/runs/${id}/explore`).then((r) => r.data)
export const getNavigation = (id) => api.get(`/runs/${id}/navigation`).then((r) => r.data)

const INGRESS_API_PREFIX = '/api/ingress'

function assetEndpoint(url) {
  if (!url) return ''
  if (url.startsWith(INGRESS_API_PREFIX)) {
    return url.slice(INGRESS_API_PREFIX.length) || '/'
  }

  try {
    const parsed = new URL(url, window.location.origin)
    const apiBase = new URL(apiBaseURL, window.location.origin)
    if (parsed.origin === apiBase.origin && parsed.pathname.startsWith(apiBase.pathname)) {
      return parsed.pathname.slice(apiBase.pathname.length) + parsed.search
    }
  } catch {
    return ''
  }

  return ''
}

export async function fetchRunAssetObjectUrl(url) {
  const endpoint = assetEndpoint(url)
  if (!endpoint) return ''
  const response = await api.get(endpoint, { responseType: 'blob' })
  return URL.createObjectURL(response.data)
}

function applyRunTick(state, onTick, data) {
  if (onTick) onTick(data)
  if (state?.status === 'failed') {
    throw new Error(state.error || 'Run failed')
  }
}

export function importPhaseDone(state) {
  if (!state) return false
  if (state.status === 'queued') return false
  if (state.import_complete) return true
  const progress = String(state.progress || '').toLowerCase()
  if (progress.includes('crawl complete')) return true
  return state.status === 'draft' && (state.progress_pct ?? 0) >= 50 && state.job_phase !== 'crawl'
}

export function explorePhaseDone(state, data) {
  if (!state) return false
  if (state.status === 'queued') return false
  if (state.status === 'running') return false
  if (state.status === 'completed') return true
  return Boolean(data?.exploration?.total_steps != null || data?.agent_report)
}

/** True when crawl (or full) audit data exists and the report page can render something useful. */
export function runHasViewableReport(state, data = {}) {
  if (!state) return false
  if (state.status === 'completed') return true
  if (data?.agent_report || data?.audit?.agent_report) return true
  if (data?.audit && state.import_complete) return true
  if (
    state.import_complete &&
    (state.overall_score != null ||
      state.readiness_score != null ||
      state.agent_accessibility_score != null)
  ) {
    return true
  }
  return false
}

export const pollTeaserRun = async (
  id,
  { intervalMs = 1000, onTick, maxWaitMs = 30_000, signal } = {}
) => {
  const hasDeadline = Number.isFinite(maxWaitMs) && maxWaitMs > 0
  const deadline = hasDeadline ? Date.now() + maxWaitMs : Infinity
  while (Date.now() < deadline) {
    if (signal?.aborted) throw new Error('Audit cancelled')
    const check = await getTeaserCheck(id)
    if (onTick) {
      onTick({
        state: {
          progress: check.progress,
          progress_pct: check.progress_pct,
          status: check.status,
          activity_log: check.activity_log
        }
      })
    }
    if (check.teaser_complete || check.status === 'completed') {
      return check
    }
    if (check.status === 'failed') {
      throw new Error('Site check failed')
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  throw new JobLongerThanExpectedError()
}

export const pollRun = async (
  id,
  { intervalMs = 1000, onTick, untilImport = false, maxWaitMs = 0, signal } = {}
) => {
  const hasDeadline = Number.isFinite(maxWaitMs) && maxWaitMs > 0
  const deadline = hasDeadline ? Date.now() + maxWaitMs : Infinity

  const tick = async () => {
    const data = await getRun(id)
    const state = data.state || {}
    applyRunTick(state, onTick, data)
    if (untilImport && importPhaseDone(state)) return data
    if (!untilImport && explorePhaseDone(state, data)) return data
    return null
  }

  for (;;) {
    if (signal?.aborted) {
      throw new Error('Audit cancelled')
    }
    const done = await tick()
    if (done) return done
    if (Date.now() > deadline) {
      throw new JobLongerThanExpectedError()
    }
    await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, intervalMs)
      if (signal) {
        signal.addEventListener(
          'abort',
          () => {
            clearTimeout(timer)
            reject(new Error('Audit cancelled'))
          },
          { once: true }
        )
      }
    })
  }
}


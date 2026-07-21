import { runHasViewableReport } from '../api/ingress'
import { normalizeSiteKey, siteLabelFromKey } from './siteKey'

export function runTimestamp(run) {
  return Date.parse(run?.updated_at || run?.created_at || '') || 0
}

export function sortRunsNewest(runs = []) {
  return [...runs].sort((a, b) => runTimestamp(b) - runTimestamp(a))
}

export function runSiteKey(run) {
  return normalizeSiteKey(run?.site_url || run?.url)
}

export function siteOptionsFromRuns(runs = []) {
  const map = new Map()
  for (const run of runs) {
    const key = runSiteKey(run)
    if (!key) continue
    map.set(key, siteLabelFromKey(key))
  }
  return [...map.entries()]
    .map(([key, label]) => ({ key, label }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

export function runsForSite(runs = [], siteKey = '') {
  if (!siteKey) return runs
  return runs.filter((run) => runSiteKey(run) === siteKey)
}

export function isActiveRun(run) {
  return run?.status === 'running' || run?.status === 'queued'
}

export function isFailedRun(run) {
  return run?.status === 'failed'
}

export function isUsableReportRun(run) {
  return !isFailedRun(run) && runHasViewableReport(run)
}

export function latestUsableRun(runs = []) {
  return sortRunsNewest(runs).find(isUsableReportRun) || null
}

export function latestRun(runs = []) {
  return sortRunsNewest(runs)[0] || null
}

export function latestFailedRun(runs = []) {
  return sortRunsNewest(runs).find(isFailedRun) || null
}

export function latestFailedAfterUsable(runs = []) {
  const failed = latestFailedRun(runs)
  const usable = latestUsableRun(runs)
  if (!failed || !usable) return null
  return runTimestamp(failed) > runTimestamp(usable) ? failed : null
}

export function filterRunsByRange(runs = [], range = '30') {
  const value = String(range || '30')
  if (value === 'all') return runs
  const days = Number(value)
  if (!Number.isFinite(days) || days <= 0) return runs
  const minTs = Date.now() - days * 24 * 60 * 60 * 1000
  return runs.filter((run) => {
    const ts = Date.parse(run?.created_at || '') || 0
    return !ts || ts >= minTs
  })
}

export function mean(values = []) {
  const nums = values.filter((n) => typeof n === 'number' && Number.isFinite(n))
  if (!nums.length) return null
  return nums.reduce((sum, n) => sum + n, 0) / nums.length
}

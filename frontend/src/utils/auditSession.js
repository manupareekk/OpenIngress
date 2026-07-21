const KEY = 'oi_active_audit'

export function saveActiveAudit({ runId, siteUrl, kind = 'standard' }) {
  if (!runId) return
  sessionStorage.setItem(
    KEY,
    JSON.stringify({
      runId,
      siteUrl: siteUrl || '',
      kind,
      savedAt: Date.now()
    })
  )
}

export function loadActiveAudit() {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    if (!data?.runId) return null
    return data
  } catch {
    return null
  }
}

export function clearActiveAudit() {
  sessionStorage.removeItem(KEY)
}

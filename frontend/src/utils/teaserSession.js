const PENDING_SITE_KEY = 'oi_pending_site'
const PENDING_FLOW_KEY = 'oi_pending_flow'

export function savePendingSite(url) {
  const site = String(url || '').trim()
  if (!site) return
  sessionStorage.setItem(PENDING_SITE_KEY, site)
  sessionStorage.setItem(PENDING_FLOW_KEY, 'teaser')
}

export function loadPendingSite() {
  try {
    const site = sessionStorage.getItem(PENDING_SITE_KEY)
    return site ? String(site).trim() : ''
  } catch {
    return ''
  }
}

export function clearPendingSite() {
  sessionStorage.removeItem(PENDING_SITE_KEY)
  sessionStorage.removeItem(PENDING_FLOW_KEY)
}

export function isTeaserFlow() {
  return sessionStorage.getItem(PENDING_FLOW_KEY) === 'teaser'
}

const NEXT_KEY = 'oi_auth_next'
const PROD_ORIGIN = 'https://www.openingress.dev'
const PROD_HOST = 'www.openingress.dev'
const PROD_ALIASES = new Set([
  'openingress.dev',
  'salmon-glacier-0418a390f.7.azurestaticapps.net'
])

export function shouldUseProdOrigin(hostname) {
  return PROD_ALIASES.has(hostname)
}

export function prodOriginUrl(pathname = '/', search = '', hash = '') {
  return `${PROD_ORIGIN}${pathname}${search}${hash}`
}

/** Stable production callback — matches Supabase allowlist and the canonical www host. */
export function authCallbackUrl() {
  const host = window.location.hostname
  if (host === PROD_HOST || shouldUseProdOrigin(host)) {
    return `${PROD_ORIGIN}/auth/callback`
  }
  return `${window.location.origin}/auth/callback`
}

/** Start OAuth only from www so PKCE storage matches the callback origin. */
export function ensureWwwBeforeAuth() {
  if (shouldUseProdOrigin(window.location.hostname)) {
    const params = new URLSearchParams(window.location.search)
    try {
      const pendingSite = sessionStorage.getItem('oi_pending_site')
      const pendingFlow = sessionStorage.getItem('oi_pending_flow')
      const authNext = sessionStorage.getItem(NEXT_KEY)
      if (pendingSite) params.set('pending_site', pendingSite)
      if (pendingFlow) params.set('pending_flow', pendingFlow)
      if (authNext) params.set('auth_next', authNext)
    } catch {
      /* ignore */
    }
    const query = params.toString()
    window.location.replace(
      prodOriginUrl(window.location.pathname, query ? `?${query}` : '', window.location.hash)
    )
    return false
  }
  return true
}

/** Restore site-check intent after apex → www redirect (sessionStorage does not carry over). */
export function restorePendingFromQuery(query) {
  const pendingSite = typeof query?.pending_site === 'string' ? query.pending_site : ''
  if (!pendingSite) return false
  sessionStorage.setItem('oi_pending_site', pendingSite)
  sessionStorage.setItem(
    'oi_pending_flow',
    typeof query?.pending_flow === 'string' ? query.pending_flow : 'teaser'
  )
  if (typeof query?.auth_next === 'string') {
    sessionStorage.setItem(NEXT_KEY, query.auth_next)
  } else {
    sessionStorage.setItem(NEXT_KEY, '/check/start')
  }
  return true
}

export function storeAuthNext(next = '/app/contact') {
  sessionStorage.setItem(NEXT_KEY, next.startsWith('/') ? next : '/app/contact')
}

export function consumeAuthNext(fallback = '/app/contact') {
  const pendingSite = sessionStorage.getItem('oi_pending_site')
  const pendingFlow = sessionStorage.getItem('oi_pending_flow')
  const stored = sessionStorage.getItem(NEXT_KEY)
  sessionStorage.removeItem(NEXT_KEY)

  if (pendingFlow === 'teaser' && pendingSite) {
    return '/check/start'
  }
  if (stored && stored.startsWith('/')) {
    return stored
  }
  return fallback
}

export function isLocalDev() {
  return (
    typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  )
}

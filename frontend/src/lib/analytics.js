const clarityProjectId = String(import.meta.env.VITE_CLARITY_PROJECT_ID || '').trim()

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1'])
const SENSITIVE_QUERY_KEYS = new Set([
  'access_token',
  'auth_next',
  'code',
  'error',
  'error_description',
  'pending_flow',
  'pending_site',
  'refresh_token',
  'url'
])

let clarityLoaded = false

function isBrowser() {
  return typeof window !== 'undefined' && typeof document !== 'undefined'
}

function analyticsEnabled() {
  if (!isBrowser() || !clarityProjectId) return false
  return !LOCAL_HOSTS.has(window.location.hostname)
}

function hasSensitiveQuery(route) {
  return Object.keys(route?.query || {}).some((key) => SENSITIVE_QUERY_KEYS.has(key))
}

function routeName(route) {
  if (typeof route?.name === 'string' && route.name) return route.name
  return 'unknown'
}

function ensureClarity() {
  if (!analyticsEnabled()) return false
  if (clarityLoaded) return typeof window.clarity === 'function'

  window.clarity =
    window.clarity ||
    function clarityQueue() {
      ;(window.clarity.q = window.clarity.q || []).push(arguments)
    }

  const script = document.createElement('script')
  script.async = true
  script.src = `https://www.clarity.ms/tag/${encodeURIComponent(clarityProjectId)}`

  const firstScript = document.getElementsByTagName('script')[0]
  firstScript.parentNode.insertBefore(script, firstScript)
  clarityLoaded = true

  return true
}

function callClarity(command, ...args) {
  if (!ensureClarity() || typeof window.clarity !== 'function') return
  window.clarity(command, ...args)
}

export function trackEvent(name) {
  if (!name) return
  callClarity('event', name)
}

export function trackRouteChange(to) {
  if (to?.name === 'auth-callback' || hasSensitiveQuery(to)) return

  const name = routeName(to)
  callClarity('set', 'route_name', name)
  callClarity('event', `page_view_${name}`)
}

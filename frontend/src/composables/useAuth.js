import { computed, reactive } from 'vue'
import { supabase, supabaseConfigured } from '../lib/supabase'
import { api } from '../lib/apiClient'
import { setAccessToken } from '../lib/authToken'
import { authenticatedHomePath } from '../config/siteLinks'
import { authCallbackUrl, ensureWwwBeforeAuth, storeAuthNext } from '../utils/authRedirect'

const state = reactive({
  user: null,
  session: null,
  credits: 0,
  isEnterprise: false,
  canRunAudit: false,
  teaserUsed: false,
  teaserAvailable: true,
  billingDisabled: false,
  billingLoaded: false,
  authReady: false
})

let initPromise = null
let authListenersAttached = false
let oauthCallbackPromise = null

const authDisabled =
  import.meta.env.VITE_AUTH_DISABLED === '1' ||
  import.meta.env.VITE_AUTH_DISABLED === 'true'

function applyDevAuth() {
  state.session = null
  state.user = {
    id: 'dev',
    email: 'dev@local',
    name: 'local dev',
    avatar: null,
    providers: ['local'],
    primaryProvider: 'local'
  }
  state.credits = null
  state.isEnterprise = true
  state.canRunAudit = true
  state.teaserUsed = false
  state.teaserAvailable = true
  state.billingDisabled = true
  state.billingLoaded = true
}

function userFromAuthUser(user) {
  if (!user) return null
  const providers = [...new Set((user.identities || []).map((i) => i.provider).filter(Boolean))]
  const meta = user.user_metadata || {}
  return {
    id: user.id,
    email: user.email || meta.email || null,
    name: meta.full_name || meta.name || user.email || 'user',
    avatar: meta.avatar_url || null,
    providers,
    primaryProvider: user.app_metadata?.provider || providers[0] || null
  }
}

async function refreshBilling() {
  if (authDisabled) {
    applyDevAuth()
    return
  }
  if (!state.session) {
    state.credits = null
    state.isEnterprise = false
    state.canRunAudit = false
    state.teaserUsed = false
    state.teaserAvailable = true
    state.billingDisabled = true
    state.billingLoaded = true
    return
  }
  try {
    const { data } = await api.get('/account/me')
    const billingDisabled = data.billing_disabled !== false
    state.billingDisabled = billingDisabled
    state.credits = billingDisabled ? null : (data.credits ?? data.balance ?? 0)
    state.isEnterprise = Boolean(data.is_enterprise)
    state.canRunAudit = data.can_run_audit !== false
    state.teaserUsed = Boolean(data.teaser_used)
    state.teaserAvailable = data.teaser_available !== false
    if (data.email && state.user) {
      state.user.email = data.email
    }
  } catch {
    state.credits = null
    state.canRunAudit = true
    state.billingDisabled = true
  } finally {
    state.billingLoaded = true
  }
}

async function applySession(session, { refreshUser = false } = {}) {
  state.session = session
  setAccessToken(session?.access_token ?? null)
  state.user = session?.user ? userFromAuthUser(session.user) : null
  if (refreshUser && supabase && session?.user) {
    const { data } = await supabase.auth.getUser()
    if (data.user) {
      state.user = userFromAuthUser(data.user)
    }
  }
}

function attachAuthListener() {
  if (!supabase || authListenersAttached) return
  authListenersAttached = true
  supabase.auth.onAuthStateChange(async (_event, session) => {
    await applySession(session)
    await refreshBilling()
  })
}

async function finishOAuthCallback() {
  if (!supabase) {
    throw new Error('Supabase is not configured')
  }

  const href = window.location.href
  const hasCode = new URL(href).searchParams.has('code')
  const hasHashToken = href.includes('access_token')

  if (hasCode) {
    const code = new URL(href).searchParams.get('code')
    if (!code) throw new Error('No auth code in callback URL')
    const { data, error } = await supabase.auth.exchangeCodeForSession(code)
    if (error) {
      const msg = error.message || ''
      if (msg.includes('flow state') || msg.includes('code verifier')) {
        await new Promise((r) => setTimeout(r, 400))
        const { data: retry } = await supabase.auth.getSession()
        if (retry.session) {
          await applySession(retry.session)
        } else {
          throw error
        }
      } else {
        throw error
      }
    } else {
      await applySession(data.session, { refreshUser: true })
    }
  } else if (hasHashToken) {
    const { data, error } = await supabase.auth.getSession()
    if (error) throw error
    if (!data.session) throw new Error('No session found after sign in')
    await applySession(data.session, { refreshUser: true })
  } else {
    throw new Error('No auth code in callback URL')
  }

  await refreshBilling()
  state.authReady = true
  attachAuthListener()
}

export async function completeOAuthCallback() {
  if (!oauthCallbackPromise) {
    oauthCallbackPromise = finishOAuthCallback().finally(() => {
      oauthCallbackPromise = null
    })
  }
  return oauthCallbackPromise
}

export async function initAuth() {
  if (initPromise) return initPromise
  initPromise = (async () => {
    try {
      if (authDisabled) {
        applyDevAuth()
        return
      }
      if (!supabase) {
        state.canRunAudit = true
        return
      }
      const { data, error } = await supabase.auth.getSession()
      if (error) throw error
      await applySession(data.session)
      await refreshBilling()
      attachAuthListener()
    } catch (err) {
      console.error('initAuth failed', err)
      state.session = null
      state.user = null
      setAccessToken(null)
      state.credits = null
      state.canRunAudit = false
    } finally {
      state.authReady = true
      state.billingLoaded = true
    }
  })()
  return initPromise
}

export function useAuth() {
  const isLoggedIn = computed(() => authDisabled || Boolean(state.user))
  const isPremium = computed(() => authDisabled || state.canRunAudit)
  const canUseApp = computed(() => authDisabled || state.canRunAudit)
  const creditBalance = computed(() => (authDisabled || state.billingDisabled ? null : state.credits))
  const teaserUsed = computed(() => Boolean(state.teaserUsed))
  const teaserAvailable = computed(() => authDisabled || Boolean(state.teaserAvailable))

  async function loginWithProvider(provider) {
    if (authDisabled) {
      applyDevAuth()
      return
    }
    if (!supabase) {
      throw new Error('Supabase is not configured')
    }
    if (!ensureWwwBeforeAuth()) return
    await supabase.auth.signOut({ scope: 'local' })
    if (!sessionStorage.getItem('oi_auth_next')) {
      const pendingSite = sessionStorage.getItem('oi_pending_site')
      const teaserFlow = sessionStorage.getItem('oi_pending_flow') === 'teaser'
      storeAuthNext(pendingSite && teaserFlow ? '/check/start' : authenticatedHomePath)
    }
    const redirectTo = authCallbackUrl()
    const options = { redirectTo, skipBrowserRedirect: false }
    if (provider === 'google') {
      options.queryParams = { prompt: 'select_account' }
    }
    if (provider === 'github') {
      options.scopes = 'read:user user:email'
    }
    const { error } = await supabase.auth.signInWithOAuth({ provider, options })
    if (error) throw error
  }

  async function logout() {
    if (authDisabled) {
      applyDevAuth()
      window.location.href = '/'
      return
    }
    if (supabase) {
      await supabase.auth.signOut()
    }
    state.user = null
    state.session = null
    setAccessToken(null)
    state.credits = null
    state.canRunAudit = false
    state.billingDisabled = true
    window.location.href = '/'
  }

  async function refreshSession() {
    if (authDisabled) {
      applyDevAuth()
      return
    }
    if (!supabase) return
    const { data } = await supabase.auth.getSession()
    await applySession(data.session)
    await refreshBilling()
  }

  return {
    state,
    isLoggedIn,
    isPremium,
    canUseApp,
    creditBalance,
    teaserUsed,
    teaserAvailable,
    authReady: computed(() => state.authReady),
    loginWithProvider,
    logout,
    refreshSession,
    refreshBilling
  }
}

export function requireAuth() {
  return authDisabled || Boolean(state.user) || !supabaseConfigured
}

export function isAuthReady() {
  return state.authReady
}

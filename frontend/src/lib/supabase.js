import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL || ''
const apiKey =
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ||
  import.meta.env.VITE_SUPABASE_ANON_KEY ||
  ''

const keyLooksValid =
  apiKey &&
  !apiKey.includes('YOUR_PROJECT') &&
  !apiKey.includes('...') &&
  apiKey.length > 20

export const supabaseConfigured = Boolean(url && keyLooksValid && !url.includes('YOUR_PROJECT'))

export const supabase = supabaseConfigured
  ? createClient(url, apiKey, {
      auth: {
        flowType: 'pkce',
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false
      }
    })
  : null

export function normalizeSiteKey(url) {
  const raw = String(url || '').trim()
  if (!raw) return ''
  try {
    const withProto = raw.startsWith('http://') || raw.startsWith('https://') ? raw : `https://${raw}`
    const parsed = new URL(withProto)
    return parsed.origin
  } catch {
    return ''
  }
}

export function siteLabelFromKey(key) {
  try {
    const parsed = new URL(key)
    return parsed.hostname.replace(/^www\./, '')
  } catch {
    return String(key || '')
  }
}


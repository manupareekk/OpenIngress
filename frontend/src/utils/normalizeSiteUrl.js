export function normalizeSiteUrl(url) {
  const value = String(url || '').trim()
  if (!value) return ''
  if (!/^https?:\/\//i.test(value)) {
    return `https://${value}`
  }
  return value
}

export function isValidSiteUrl(url) {
  const normalized = normalizeSiteUrl(url)
  if (!normalized) return false
  try {
    const parsed = new URL(normalized)
    return Boolean(parsed.hostname && parsed.hostname.includes('.'))
  } catch {
    return false
  }
}

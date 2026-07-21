const BRAND = 'OpenIngress'

export function withBrand(text) {
  if (!text) return ''
  return String(text).replace(/OpenIngress/g, `<span class="normal-case">${BRAND}</span>`)
}

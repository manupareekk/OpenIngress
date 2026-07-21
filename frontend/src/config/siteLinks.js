const defaultGithubUrl = 'https://github.com/Open-Ingress/OpenIngress'

export const githubUrl = String(import.meta.env.VITE_GITHUB_URL || defaultGithubUrl).trim()
export const demoReportSlug = String(
  import.meta.env.VITE_PUBLIC_DEMO_REPORT_SLUG || 'agent-fragile-storefront'
).trim()
export const authenticatedHomePath = '/app'

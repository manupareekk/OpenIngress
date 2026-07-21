<script setup>
import { computed } from 'vue'
import AgentExportPanel from './AgentExportPanel.vue'
import ReportCollapsible from './ReportCollapsible.vue'
import OperatorTraceCard from '../open-ingress/OperatorTraceCard.vue'
import UserJourneyTable from './UserJourneyTable.vue'
import { runHasViewableReport } from '../../api/ingress'

const props = defineProps({
  payload: { type: Object, required: true },
  traces: { type: Array, default: () => [] },
  screenshotObjectUrls: { type: Object, default: () => ({}) },
  heroImage: { type: String, default: '' },
  showEvidenceImages: { type: Boolean, default: false },
  showExports: { type: Boolean, default: true },
  proofOnly: { type: Boolean, default: false },
  flowOnly: { type: Boolean, default: false },
  flowStepId: { type: String, default: '' },
  runPath: { type: String, default: '' }
})

/** Defense for old persisted runs that still carry commerce packaging copy. */
const COMMERCE_NOISE = [
  'ai shopper',
  'shopify',
  'revenue at risk',
  'buyer funnel',
  'checkout handoff',
  'agency handoff',
  'commerce dashboard',
  'revenue multiplier'
]

const isCommerceNoise = (value) => {
  const text = String(value || '').toLowerCase()
  return COMMERCE_NOISE.some((token) => text.includes(token))
}

const state = computed(() => props.payload?.state || {})
const audit = computed(() => props.payload?.audit || {})
const combined = computed(() => props.payload?.combined_report || null)
const agentReport = computed(
  () => props.payload?.agent_report || audit.value?.agent_report || null
)
const exports = computed(() => props.payload?.exports || {})
const coverage = computed(() => audit.value?.coverage || {})
const hasExplore = computed(() => Boolean(agentReport.value?.has_exploration))

const userJourneys = computed(() => {
  const fromExports = exports.value.user_journeys
  if (Array.isArray(fromExports) && fromExports.length) {
    return fromExports.filter((row) => !isCommerceNoise(row?.job) && !isCommerceNoise(row?.result))
  }
  const fromReport = agentReport.value?.job_results
  if (Array.isArray(fromReport) && fromReport.length) {
    return fromReport.filter((row) => !isCommerceNoise(row?.job) && !isCommerceNoise(row?.result))
  }
  return []
})

const exploreIncomplete = computed(() => {
  if (hasExplore.value) return false
  return runHasViewableReport(state.value, props.payload) && state.value?.import_complete
})

const exploreMetrics = computed(() => agentReport.value?.efficiency || null)

const auditChecks = computed(() =>
  (exports.value.checks || []).filter(
    (check) => !isCommerceNoise(check?.title) && !isCommerceNoise(check?.detail)
  )
)

const fixes = computed(() => {
  const rows = hasExplore.value
    ? agentReport.value?.fixes || exports.value.fixes || []
    : exports.value.fixes || []
  return rows.filter((row) => !isCommerceNoise(row?.title) && !isCommerceNoise(row?.summary))
})

const gaps = computed(() => {
  const rows = agentReport.value?.gaps || []
  return rows.filter((row) => !isCommerceNoise(row?.title) && !isCommerceNoise(row?.summary) && !isCommerceNoise(row?.text))
})

const breakPoints = computed(() => {
  const rows = []
  const seen = new Set()
  const push = (item, fallbackTitle) => {
    const title = item?.title || item?.summary || item?.text || item?.gap || fallbackTitle
    if (!title || isCommerceNoise(title)) return
    const key = `${title}|${item?.step || item?.job || ''}`
    if (seen.has(key)) return
    seen.add(key)
    rows.push({
      key,
      title,
      step: item?.step || item?.job || item?.impact_area || 'Agent path',
      detail: item?.detail || item?.evidence || item?.blocker || item?.summary || item?.text || '',
      severity: item?.severity || item?.priority || item?.status || 'medium'
    })
  }
  for (const gap of gaps.value) push(gap, 'Coverage gap')
  for (const fix of fixes.value) push(fix, 'Fix candidate')
  for (const journey of userJourneys.value) {
    const status = String(journey?.status || '').toLowerCase()
    if (status === 'failed' || status === 'partial' || journey?.blocker) {
      push(
        {
          title: journey.job || journey.id || 'Agent job blocked',
          step: journey.job || journey.id || 'Agent job',
          detail: journey.blocker || journey.result || '',
          severity: status === 'failed' ? 'high' : 'medium'
        },
        'Agent job blocked'
      )
    }
  }
  return rows
})

const onSiteActionTotal = computed(() => {
  const total = Number(coverage.value?.total_actions || 0)
  const external = Number(coverage.value?.external_actions || 0)
  return Math.max(0, total - external)
})

const externalActionCount = computed(() => Number(coverage.value?.external_actions || 0))

const staticCoverageDisplay = computed(() => {
  if (onSiteActionTotal.value === 0) return 'N/A'
  const value = audit.value?.agent_accessibility_score ?? coverage.value?.action_accessibility_percent
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Math.round(Number(value))}%`
})

const staticCoverageNote = computed(() => {
  if (onSiteActionTotal.value === 0) {
    return 'No on-site actions were discovered in the crawl graph.'
  }
  const accessible = Number(coverage.value?.accessible_actions || 0)
  return `${accessible}/${onSiteActionTotal.value} on-site actions resolved from the crawl graph.`
})

const missedActionsDisplay = computed(() => {
  if (onSiteActionTotal.value === 0) return 'N/A'
  const value = exploreMetrics.value?.actions_lost_percent
  if (value == null || Number.isNaN(Number(value))) return ''
  const num = Number(value)
  return `${Number.isInteger(num) ? num : Math.round(num * 10) / 10}%`
})

const missedActionsNote = computed(() => {
  if (onSiteActionTotal.value === 0) {
    return externalActionCount.value > 0
      ? 'No on-site actions were found, so external exits are tracked separately below.'
      : 'No on-site actions were found in the crawl graph.'
  }
  return 'Important actions the agent could not reach or complete.'
})

const reportBusinessSummary = computed(() => {
  const lines = (exports.value.business_summary || []).filter((line) => !isCommerceNoise(line))
  if (onSiteActionTotal.value > 0) return lines
  return lines.filter((line) => {
    const lower = String(line || '').toLowerCase()
    return !(
      (lower.includes('catalog action') && (lower.includes('missed') || lower.includes('unreachable'))) ||
      (lower.includes('on-site action') && lower.includes('never reached'))
    )
  })
})

const secondaryMetrics = computed(() => {
  const items = []
  if (externalActionCount.value > 0) {
    items.push({
      stat: String(externalActionCount.value),
      body:
        externalActionCount.value === 1
          ? 'External exit found in the crawl catalog'
          : 'External exits found in the crawl catalog'
    })
  }
  return items
})

const hasEvidence = computed(
  () =>
    Boolean(agentReport.value?.findings?.length) ||
    Boolean(props.showEvidenceImages && props.heroImage && hasExplore.value) ||
    Boolean(props.showEvidenceImages && props.traces.length > 0)
)

const siteHost = computed(() => {
  const rawUrl = combined.value?.source_url || state.value?.site_url || props.payload?.draft?.siteUrl || ''
  if (!rawUrl) return 'Submitted site'
  try {
    const normalized = rawUrl.startsWith('http') ? rawUrl : `https://${rawUrl}`
    return new URL(normalized).hostname.replace(/^www\./, '')
  } catch {
    return rawUrl.replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, '')
  }
})

const reportScore = computed(() => audit.value.overall_score ?? audit.value.readiness_score ?? null)

const pctDisplay = (value) => {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const num = Number(value)
  return `${Number.isInteger(num) ? num : Math.round(num * 10) / 10}%`
}

const summaryMetrics = computed(() => [
  {
    label: 'Readiness',
    value: reportScore.value == null ? '—' : Math.round(Number(reportScore.value)),
    note: exports.value.verdict || 'Latest completed agent run.'
  },
  {
    label: 'Static coverage',
    value: staticCoverageDisplay.value,
    note: staticCoverageNote.value
  },
  {
    label: 'Missed actions',
    value: missedActionsDisplay.value || '—',
    note: missedActionsNote.value
  },
  {
    label: 'Extra navigation',
    value: pctDisplay(exploreMetrics.value?.step_waste_percent),
    note: 'Extra steps beyond the shortest estimated path.'
  }
])

const appendixMeta = computed(() => {
  const parts = []
  if (fixes.value.length) parts.push(`${fixes.value.length} fixes`)
  if (auditChecks.value.length) parts.push(`${auditChecks.value.length} checks`)
  if (hasEvidence.value) parts.push('evidence')
  return parts.join(' · ')
})

const checkStatusLabel = (status) => {
  if (status === 'pass') return 'Pass'
  if (status === 'warn') return 'Warn'
  if (status === 'fail') return 'Fail'
  return status || 'Unknown'
}

const checkBadgeClass = (status) => {
  if (status === 'fail') return 'border-[#B42318] text-[#B42318]'
  if (status === 'warn') return 'border-[#CA8A04] text-[#92400E]'
  return 'border-[#15803D] text-[#15803D]'
}

const focusedJourney = computed(() => {
  if (!props.flowOnly || !props.flowStepId) return null
  const needle = String(props.flowStepId || '').toLowerCase()
  return (
    userJourneys.value.find((row) => {
      const id = String(row?.id || row?.job || '')
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, '-')
        .replace(/^-+|-+$/g, '')
      return id === needle
    }) || null
  )
})

const focusedJourneyGaps = computed(() => {
  const journey = focusedJourney.value
  if (!journey) return []
  const attached = Array.isArray(journey.gaps) ? journey.gaps : []
  if (attached.length) {
    return attached.filter((gap) => !isCommerceNoise(gap?.label) && !isCommerceNoise(gap?.impact))
  }
  // Fallback for older runs that only stored a gap count string on blocker.
  const jobId = String(journey.id || '').toLowerCase()
  const pageHints = new Set(
    [jobId, jobId.replace(/^book_/, ''), jobId.replace(/^find_/, ''), jobId.replace(/^open_/, '')].filter(Boolean)
  )
  const result = String(journey.result || '')
  const pathMatch = result.match(/\/[\w./-]*/)
  const pathHint = pathMatch ? pathMatch[0].replace(/\/+$/, '') : ''
  if (pathHint && pathHint !== '/') {
    pageHints.add(pathHint.replace(/^\//, '').split('/')[0])
  }
  const allGaps = Array.isArray(gaps.value) ? gaps.value : []
  const matched = allGaps.filter((gap) => {
    const pageId = String(gap?.page_id || '').toLowerCase()
    if (pageId && pageHints.has(pageId)) return true
    const path = String(gap?.path || gap?.selector || '').toLowerCase()
    if (pathHint && pathHint !== '/' && path.includes(pathHint.toLowerCase())) return true
    return false
  })
  return matched
    .slice(0, 8)
    .filter((gap) => !isCommerceNoise(gap?.label) && !isCommerceNoise(gap?.impact))
})
</script>

<template>
  <div class="mx-auto max-w-[1120px] space-y-lg">
    <template v-if="proofOnly">
      <section class="oi-dash-card" style="overflow:hidden;">
        <div class="border-b border-[#eeeeee] p-md">
          <p class="text-label-md normal-case text-[#888888]">{{ siteHost }}</p>
          <h1 class="mt-xs text-title-md font-medium normal-case text-[#111111]">Agent proof</h1>
          <p class="mt-xs max-w-[720px] text-body-md normal-case leading-relaxed text-[#666666]">
            Screenshots and operator traces from the live explore pass.
          </p>
        </div>
        <div class="space-y-lg p-md">
          <div v-if="showEvidenceImages && heroImage && hasExplore" class="border border-[#eeeeee] p-xs">
            <img :src="heroImage" alt="Site screenshot from agent explore" class="w-full grayscale-[0.15]" />
          </div>
          <OperatorTraceCard
            v-if="showEvidenceImages && traces.length && hasExplore"
            :traces="traces"
            :screenshot-object-urls="screenshotObjectUrls"
          />
          <p v-else class="text-body-md normal-case text-[#666666]">
            No proof artifacts yet for this run.
          </p>
        </div>
      </section>
    </template>

    <template v-else-if="flowOnly">
      <section class="oi-dash-card" style="overflow:hidden;">
        <div class="border-b border-[#eeeeee] p-md">
          <p class="text-label-md normal-case text-[#888888]">{{ siteHost }}</p>
          <h1 class="mt-xs text-title-md font-medium normal-case text-[#111111]">
            {{ focusedJourney?.job || 'Agent job' }}
          </h1>
          <p class="mt-xs max-w-[720px] text-body-md normal-case leading-relaxed text-[#666666]">
            {{ focusedJourney?.goal || focusedJourney?.result || 'Detail for the selected agent job from this run.' }}
          </p>
          <p
            v-if="focusedJourney?.result"
            class="mt-xs text-body-md normal-case text-[#888888]"
          >
            {{ focusedJourney.result }}
          </p>
        </div>
        <div class="space-y-md p-md">
          <dl class="grid gap-sm text-body-md normal-case md:grid-cols-2">
            <div>
              <dt class="text-label-md text-[#888888]">Status</dt>
              <dd class="mt-[2px] text-[#333333]">{{ focusedJourney?.status || '—' }}</dd>
            </div>
            <div v-if="focusedJourney?.blocker && focusedJourney.blocker !== '—'">
              <dt class="text-label-md text-[#888888]">Summary</dt>
              <dd class="mt-[2px] text-[#666666]">{{ focusedJourney.blocker }}</dd>
            </div>
          </dl>

          <div v-if="focusedJourneyGaps.length" class="space-y-sm">
            <p class="text-body-md font-medium normal-case text-[#111111]">Break points on this job</p>
            <ul class="divide-y divide-[#eeeeee] border border-[#eeeeee] bg-white">
              <li
                v-for="gap in focusedJourneyGaps"
                :key="gap.id || gap.label"
                class="flex flex-col gap-xs px-md py-sm md:flex-row md:items-start md:justify-between md:gap-md"
              >
                <div class="min-w-0">
                  <p class="text-body-md font-medium normal-case text-[#111111]">
                    {{ gap.label || gap.type || 'Gap' }}
                  </p>
                  <p v-if="gap.path" class="mt-xs text-label-md normal-case text-[#888888]">
                    {{ gap.path }}
                  </p>
                  <p
                    v-if="gap.impact"
                    class="mt-xs text-body-md normal-case leading-relaxed text-[#666666]"
                  >
                    {{ gap.impact }}
                  </p>
                </div>
                <span
                  class="inline-flex shrink-0 rounded-full border border-[#eeeeee] px-xs py-[2px] text-label-md uppercase text-[#666666]"
                >
                  {{ gap.severity || 'medium' }}
                </span>
              </li>
            </ul>
          </div>
          <p
            v-else-if="focusedJourney?.status === 'partial' || focusedJourney?.status === 'failed'"
            class="border border-[#eeeeee] bg-[#fafafa] px-md py-sm text-body-md normal-case text-[#666666]"
          >
            No gap details were attached to this job. Check Break points on the main report, or re-run the study.
          </p>
        </div>
      </section>
    </template>

    <template v-else>
      <section id="run-coverage" class="oi-dash-card" style="overflow:hidden;">
        <div class="border-b border-[#eeeeee] p-md">
          <p class="text-label-md normal-case text-[#888888]">{{ siteHost }}</p>
          <h1 class="mt-xs text-title-md font-medium normal-case text-[#111111]">
            Agent readiness report
          </h1>
          <p class="mt-xs max-w-[720px] text-body-md normal-case leading-relaxed text-[#666666]">
            Paste any URL → crawl → agent explore. Coverage and where agents break.
          </p>
        </div>
        <div class="grid gap-0 md:grid-cols-4">
          <article
            v-for="metric in summaryMetrics"
            :key="metric.label"
            class="border-b border-[#eeeeee] p-md md:border-b-0 md:border-r"
          >
            <p class="text-label-md text-[#888888]">{{ metric.label }}</p>
            <p class="mt-xs text-title-sm font-medium normal-case text-[#111111]">{{ metric.value }}</p>
            <p class="mt-xs text-label-md normal-case leading-snug text-[#666666]">{{ metric.note }}</p>
          </article>
        </div>
      </section>

      <section id="run-jobs">
        <UserJourneyTable :journeys="userJourneys" :explore-complete="hasExplore" />
      </section>

      <section id="run-breakers" class="space-y-sm">
        <h3 class="text-body-lg font-medium text-[#111111]">Break points</h3>
        <p class="text-body-md normal-case text-[#666666]">
          Where the agent failed, stalled, or needs a fix before it can continue.
        </p>
        <div
          v-if="!breakPoints.length"
          class="border border-[#e5e5e5] bg-white px-md py-sm text-body-md normal-case text-[#666666]"
        >
          {{
            exploreIncomplete
              ? 'Agent exploration did not complete. Re-run the agent audit to surface break points.'
              : 'No break points recorded for this run.'
          }}
        </div>
        <ul v-else class="divide-y divide-[#eeeeee] border border-[#eeeeee] bg-white">
          <li
            v-for="item in breakPoints.slice(0, 12)"
            :key="item.key"
            class="flex flex-col gap-xs px-md py-sm md:flex-row md:items-start md:justify-between md:gap-md"
          >
            <div class="min-w-0">
              <p class="text-body-md font-medium normal-case text-[#111111]">{{ item.title }}</p>
              <p class="mt-xs text-label-md normal-case text-[#888888]">{{ item.step }}</p>
              <p v-if="item.detail" class="mt-xs text-body-md normal-case leading-relaxed text-[#666666]">
                {{ item.detail }}
              </p>
            </div>
            <span class="inline-flex shrink-0 rounded-full border border-[#eeeeee] px-xs py-[2px] text-label-md uppercase text-[#666666]">
              {{ item.severity }}
            </span>
          </li>
        </ul>
      </section>

      <p
        v-if="!hasExplore"
        class="border border-[#e5e5e5] bg-white px-md py-sm text-body-md text-[#666666]"
      >
        Agent exploration did not complete. Re-run the agent audit for live gaps and activation metrics.
      </p>

      <ReportCollapsible title="Technical appendix" :meta="appendixMeta">
        <div class="space-y-lg p-md md:p-lg">
          <section v-if="reportBusinessSummary.length || secondaryMetrics.length" class="space-y-sm">
            <p class="text-body-md font-medium normal-case text-[#111111]">Run notes</p>
            <ul class="divide-y divide-[#eeeeee] border border-[#eeeeee] bg-white">
              <li
                v-for="line in reportBusinessSummary"
                :key="line"
                class="px-md py-sm text-body-md normal-case text-[#555555]"
              >
                {{ line }}
              </li>
              <li
                v-for="item in secondaryMetrics"
                :key="item.body"
                class="px-md py-sm text-body-md normal-case text-[#555555]"
              >
                <span class="font-medium text-[#111111]">{{ item.stat }}</span> {{ item.body }}
              </li>
            </ul>
          </section>


          <section v-if="auditChecks.length" class="space-y-sm">
            <p class="text-body-md font-medium normal-case text-[#111111]">Checks</p>
            <ul class="divide-y divide-[#eeeeee] border border-[#eeeeee] bg-white">
              <li
                v-for="check in auditChecks"
                :key="check.id"
                class="flex flex-col gap-xs px-md py-sm md:flex-row md:items-start md:justify-between md:gap-md"
              >
                <div class="min-w-0">
                  <p class="text-body-md font-medium normal-case text-[#111111]">{{ check.title }}</p>
                  <p class="mt-xs text-body-md normal-case leading-relaxed text-[#666666]">{{ check.detail }}</p>
                </div>
                <span
                  class="inline-flex shrink-0 rounded-full border px-xs py-[2px] text-label-md uppercase"
                  :class="checkBadgeClass(check.status)"
                >
                  {{ checkStatusLabel(check.status) }}
                </span>
              </li>
            </ul>
          </section>

          <AgentExportPanel
            v-if="showExports"
            :report-md="exports.report_md"
          />

          <section v-if="hasEvidence" class="space-y-lg">
            <p class="text-body-md font-medium normal-case text-[#111111]">Agent evidence</p>

            <section v-if="agentReport?.findings?.length" class="space-y-sm">
              <p class="text-label-md text-[#888888]">What the agent found</p>
              <ul class="divide-y divide-[#eeeeee] border border-[#eeeeee] bg-[#fafafa]">
                <li
                  v-for="(item, i) in agentReport.findings"
                  :key="i"
                  class="px-md py-sm text-body-md normal-case text-[#666666]"
                >
                  {{ item.text }}
                </li>
              </ul>
            </section>

            <div v-if="showEvidenceImages && heroImage && hasExplore" class="border border-[#eeeeee] p-xs">
              <img :src="heroImage" alt="Site screenshot from agent explore" class="w-full grayscale-[0.15]" />
            </div>

            <OperatorTraceCard
              v-if="showEvidenceImages && traces.length && hasExplore"
              :traces="traces"
              :screenshot-object-urls="screenshotObjectUrls"
            />
          </section>
        </div>
      </ReportCollapsible>
    </template>
  </div>
</template>

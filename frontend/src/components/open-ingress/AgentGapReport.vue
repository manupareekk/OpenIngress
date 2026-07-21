<template>
  <div v-if="report" class="space-y-lg">
    <!-- Hero -->
    <section class="bg-primary-container text-on-primary-container p-lg md:p-xl grid grid-cols-1 md:grid-cols-2 gap-xl items-center">
      <div v-if="heroImage" class="order-2 md:order-1">
        <div class="border border-on-primary-container/20 p-xs bg-black/20">
          <img :src="heroImage" alt="Site screenshot" class="w-full h-auto grayscale-[0.2] brightness-90" />
        </div>
      </div>
      <div class="order-1 md:order-2 flex flex-col justify-center gap-lg">
        <div class="space-y-sm">
          <h2 class="text-headline-md text-on-primary font-medium">Audit summary</h2>
          <p class="text-body-md text-on-primary-container max-w-md">{{ report.summary }}</p>
          <p v-if="report.exploration_mode" class="text-label-md opacity-70">
            {{ report.exploration_mode }}<span v-if="report.llm_enabled"> · LLM navigation</span>
          </p>
        </div>
        <div v-if="efficiency" class="grid grid-cols-3 gap-md">
          <div>
            <div class="text-headline-md text-on-primary font-bold">{{ efficiency.total_agent_steps || '—' }}</div>
            <div class="text-label-md opacity-70">Total steps</div>
          </div>
          <div>
            <div class="text-headline-md text-on-primary font-bold">{{ efficiency.step_waste_percent }}%</div>
            <div class="text-label-md opacity-70">Step waste</div>
          </div>
          <div>
            <div class="text-headline-md text-on-primary font-bold">{{ efficiency.actions_lost_percent }}%</div>
            <div class="text-label-md opacity-70">Actions lost</div>
          </div>
        </div>
      </div>
    </section>

    <!-- Metrics -->
    <section v-if="efficiency">
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-gutter">
        <div v-for="metric in metricCards" :key="metric.label" class="bg-surface-container-lowest border border-outline-variant p-md">
          <div class="flex justify-between items-start mb-lg">
            <span class="text-label-md text-secondary">{{ metric.label }}</span>
            <span class="material-symbols-outlined text-secondary text-[20px]">{{ metric.icon }}</span>
          </div>
          <div class="text-headline-lg mb-xs">{{ metric.value }}</div>
          <div class="text-body-md text-secondary">{{ metric.detail }}</div>
        </div>
      </div>
    </section>

    <!-- Findings -->
    <section v-if="findings.length" class="border border-outline-variant bg-surface-container-lowest">
      <div class="p-md border-b border-outline-variant">
        <h3 class="text-headline-md font-medium">What the agent found</h3>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-outline-variant">
        <div v-for="(item, i) in findings.slice(0, 9)" :key="i" class="p-md space-y-sm">
          <div class="text-label-md font-bold text-primary uppercase tracking-wide">{{ findingKind(item.kind) }}</div>
          <p class="text-body-md" :class="item.kind === 'failure' ? 'text-error' : 'text-secondary'">{{ item.text }}</p>
        </div>
      </div>
    </section>

    <!-- Gaps -->
    <section v-if="gaps.length" class="space-y-md">
      <h3 class="text-headline-md font-medium px-xs">Gaps blocking agents</h3>
      <div class="space-y-px bg-outline-variant border border-outline-variant">
        <div
          v-for="gap in gaps"
          :key="gap.id"
          class="bg-surface-container-lowest p-md flex flex-col md:flex-row justify-between items-start md:items-center gap-md"
        >
          <div class="flex items-start gap-md min-w-0">
            <span class="material-symbols-outlined text-secondary shrink-0">link_off</span>
            <div class="min-w-0">
              <div class="text-body-lg font-medium">{{ gap.label || gap.type }}</div>
              <div class="text-body-md text-secondary">{{ gap.impact }}</div>
              <div v-if="gap.page_id" class="text-label-md text-secondary mt-xs">{{ gap.page_id }}</div>
            </div>
          </div>
          <div class="flex gap-xs flex-wrap shrink-0">
            <span class="bg-surface-container-low text-secondary px-sm py-xs text-label-md rounded-xl capitalize">{{ gap.severity }}</span>
            <span class="bg-surface-container-low text-secondary px-sm py-xs text-label-md rounded-xl">{{ gap.type }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Fixes -->
    <section v-if="fixes.length" class="space-y-md">
      <h3 class="text-headline-md font-medium px-xs">Exact changes to make</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-gutter">
        <div v-for="(fix, i) in fixes" :key="i" class="border border-outline-variant p-md flex flex-col gap-md">
          <div class="flex justify-between items-center">
            <span class="text-label-md text-primary font-bold">FIX {{ String(i + 1).padStart(2, '0') }}</span>
            <span class="text-label-md font-bold uppercase" :class="priorityClass(fix.priority)">{{ fix.priority }}</span>
          </div>
          <p class="text-body-md text-on-surface-variant">{{ fix.change }}</p>
        </div>
      </div>
    </section>

    <!-- Action map -->
    <section v-if="actions.length" class="space-y-md">
      <h3 class="text-headline-md font-medium px-xs">On-site action map</h3>
      <div class="border border-outline-variant overflow-x-auto">
        <table class="w-full text-body-md border-collapse min-w-[640px]">
          <thead>
            <tr class="border-b border-outline-variant bg-surface-container-low text-left text-label-md text-secondary">
              <th class="p-md font-medium">Label</th>
              <th class="p-md font-medium">Page</th>
              <th class="p-md font-medium">Catalog</th>
              <th class="p-md font-medium">Aria</th>
              <th class="p-md font-medium">Activated</th>
              <th class="p-md font-medium">Gap</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in actions" :key="row.id" class="border-b border-outline-variant">
              <td class="p-md">{{ row.label }}</td>
              <td class="p-md text-secondary">{{ row.page_id }}</td>
              <td class="p-md">{{ row.catalog_accessible ? 'OK' : 'Blocked' }}</td>
              <td class="p-md">{{ row.aria_matched ? 'Yes' : 'No' }}</td>
              <td class="p-md">{{ row.agent_activated ? 'Yes' : 'No' }}</td>
              <td class="p-md text-secondary">{{ row.gap || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="!report.has_exploration" class="border border-dashed border-outline-variant p-md rounded-lg text-body-md text-secondary">
      Crawl-only data. Run the Cursor agent pass to populate findings and wasted-effort metrics.
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  report: { type: Object, default: null },
  heroImage: { type: String, default: '' }
})

const efficiency = computed(() => props.report?.efficiency || null)
const findings = computed(() => props.report?.findings || [])
const gaps = computed(() => props.report?.gaps || [])
const fixes = computed(() => props.report?.fixes || [])
const actions = computed(() => props.report?.actions || [])

const metricCards = computed(() => {
  const e = efficiency.value
  if (!e) return []
  return [
    { label: 'Actions lost', icon: 'warning', value: `${e.actions_lost_percent}%`, detail: `${e.not_activated_actions}/${e.on_site_actions} not activated` },
    { label: 'Time lost (est.)', icon: 'schedule', value: `${e.time_lost_percent}%`, detail: `~${e.estimated_wasted_time_sec}s of ${e.estimated_total_time_sec}s` },
    { label: 'Step waste', icon: 'analytics', value: `${e.step_waste_percent}%`, detail: `${e.redundant_steps} redundant steps` },
    { label: 'Gaps', icon: 'space_bar', value: String(e.gap_count), detail: `${e.critical_gaps} critical · ${e.high_gaps} high` },
    { label: 'Catalog blocked', icon: 'block', value: `${e.catalog_loss_percent}%`, detail: `${e.catalog_blocked_actions} actions` },
    { label: 'Aria tree gap', icon: 'account_tree', value: `${e.aria_gap_percent}%`, detail: 'Live tree vs crawl catalog' }
  ]
})

const findingKind = (kind) => {
  const map = { product: 'Product', coverage: 'Coverage', action: 'Action', failure: 'Failure', crawl: 'Crawl' }
  return map[kind] || 'Finding'
}

const priorityClass = (p) => {
  if (p === 'critical') return 'text-error'
  if (p === 'high') return 'text-on-surface-variant'
  return 'text-secondary'
}
</script>

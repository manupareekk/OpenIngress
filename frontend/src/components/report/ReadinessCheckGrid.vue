<script setup>
import { computed } from 'vue'
import ReportCollapsible from './ReportCollapsible.vue'

const props = defineProps({
  checks: { type: Array, default: () => [] }
})

const passCount = computed(() => props.checks.filter((c) => c.status === 'pass').length)
const failCount = computed(() => props.checks.filter((c) => c.status === 'fail').length)
const warnCount = computed(() => props.checks.filter((c) => c.status === 'warn').length)

const meta = computed(() => {
  const parts = [`${passCount.value} Pass`]
  if (warnCount.value) parts.push(`${warnCount.value} Warn`)
  if (failCount.value) parts.push(`${failCount.value} Fail`)
  return parts.join(' · ')
})

const statusLabel = (status) => {
  if (status === 'pass') return 'Pass'
  if (status === 'warn') return 'Warn'
  if (status === 'fail') return 'Fail'
  return status
}

const dotClass = (status) => {
  if (status === 'fail') return 'bg-[#B42318]'
  if (status === 'warn') return 'bg-[#CA8A04]'
  return 'bg-[#15803D]'
}

const badgeClass = (status) => {
  if (status === 'fail') return 'border-[#B42318] text-[#B42318]'
  if (status === 'warn') return 'border-[#CA8A04] text-[#92400E]'
  return 'border-[#15803D] text-[#15803D]'
}
</script>

<template>
  <ReportCollapsible v-if="checks.length" title="Checks" :meta="meta">
    <ul class="divide-y divide-[#eeeeee]">
      <li
        v-for="check in checks"
        :key="check.id"
        class="flex flex-col gap-xs px-md py-sm md:flex-row md:items-start md:justify-between md:gap-md md:px-lg"
      >
        <div class="min-w-0 flex-1 space-y-xs">
          <div class="flex items-center gap-sm">
            <span class="inline-flex h-2 w-2 shrink-0 rounded-full" :class="dotClass(check.status)" aria-hidden="true" />
            <span class="text-body-md font-medium normal-case text-[#111111]">{{ check.title }}</span>
          </div>
          <p class="pl-[14px] text-body-md normal-case leading-relaxed text-[#666666]">{{ check.detail }}</p>
          <p v-if="check.fix_hint" class="pl-[14px] text-body-md normal-case text-[#888888]">
            → {{ check.fix_hint }}
          </p>
        </div>
        <span
          class="inline-flex w-[4.75rem] shrink-0 items-center justify-center self-start rounded-full border border-[#eeeeee] py-[2px] text-label-md uppercase tracking-wide"
          :class="badgeClass(check.status)"
        >
          {{ statusLabel(check.status) }}
        </span>
      </li>
    </ul>
  </ReportCollapsible>
</template>

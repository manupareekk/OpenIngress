<script setup>
import { computed } from 'vue'

const props = defineProps({
  journeys: { type: Array, default: () => [] },
  exploreComplete: { type: Boolean, default: false }
})

const ORDER = {
  orient: 0,
  portfolio: 10,
  product: 15,
  find_product: 18,
  add_to_cart: 19,
  pricing: 20,
  checkout: 21,
  book_demo: 22,
  convert: 25,
  blog: 30,
  about: 35,
  contact: 40
}

const attemptedJourneys = computed(() =>
  (props.journeys || []).filter((row) => {
    const result = String(row?.result || '').toLowerCase().trim()
    const blocker = String(row?.blocker || '').toLowerCase()
    return result !== 'not attempted' && !blocker.includes('did not attempt')
  })
)

const sortedJourneys = computed(() =>
  [...attemptedJourneys.value].sort(
    (a, b) => (ORDER[a.id] ?? 99) - (ORDER[b.id] ?? 99) || String(a.job).localeCompare(String(b.job))
  )
)

const statusLabel = (status) => {
  if (status === 'success') return 'Pass'
  if (status === 'partial') return 'Partial'
  if (status === 'failed') return 'Blocked'
  return 'Unknown'
}

const statusClass = (status) => {
  if (status === 'success') return 'border-[#15803D] bg-[#15803D] text-white'
  if (status === 'partial') return 'border-[#CA8A04] bg-white text-[#92400E]'
  if (status === 'failed') return 'border-[#B42318] bg-white text-[#B42318]'
  return 'border-[#eeeeee] bg-white text-[#888888]'
}
</script>

<template>
  <section class="space-y-sm">
    <h3 class="text-body-lg font-medium text-[#111111]">Agent jobs</h3>
    <p class="text-body-md normal-case text-[#666666]">
      Attempted jobs from your crawl catalog, ordered by typical user intent.
    </p>

    <div
      v-if="!sortedJourneys.length"
      class="border border-[#e5e5e5] bg-white px-md py-sm text-body-md normal-case text-[#666666]"
    >
      <template v-if="exploreComplete">
        No job results yet. Re-run agent to score journeys against your site catalog.
      </template>
      <template v-else>
        Run the agent audit to see which user jobs the agent can complete.
      </template>
    </div>

    <div v-else class="space-y-sm md:space-y-0">
      <div class="grid gap-sm md:hidden">
        <article
          v-for="row in sortedJourneys"
          :key="row.id"
          class="border border-[#e5e5e5] bg-white p-md"
        >
          <div class="flex flex-wrap items-start justify-between gap-sm">
            <p class="text-body-md font-medium text-[#111111]">{{ row.job }}</p>
            <span
              class="inline-flex w-[4.75rem] items-center justify-center rounded-full border py-[2px] text-label-md capitalize"
              :class="statusClass(row.status)"
            >
              {{ statusLabel(row.status) }}
            </span>
          </div>
          <dl class="mt-sm grid gap-xs text-body-md normal-case">
            <div>
              <dt class="text-label-md text-[#888888]">Result</dt>
              <dd class="mt-[2px] text-[#333333]">{{ row.result }}</dd>
            </div>
            <div v-if="row.blocker">
              <dt class="text-label-md text-[#888888]">Blocker</dt>
              <dd class="mt-[2px] text-[#666666]">{{ row.blocker }}</dd>
            </div>
          </dl>
        </article>
      </div>

      <div class="hidden overflow-x-auto border border-[#e5e5e5] bg-white md:block">
      <table class="w-full min-w-[560px] text-left text-body-md normal-case">
        <thead class="border-b border-[#eeeeee] text-label-md text-[#888888]">
          <tr>
            <th class="px-md py-sm font-medium">Job</th>
            <th class="px-md py-sm font-medium">Status</th>
            <th class="px-md py-sm font-medium">Result</th>
            <th class="px-md py-sm font-medium">Blocker</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-[#eeeeee]">
          <tr v-for="row in sortedJourneys" :key="row.id">
            <td class="px-md py-sm font-medium text-[#111111]">{{ row.job }}</td>
            <td class="px-md py-sm">
              <span
                class="inline-flex w-[4.75rem] items-center justify-center rounded-full border py-[2px] text-label-md capitalize"
                :class="statusClass(row.status)"
              >
                {{ statusLabel(row.status) }}
              </span>
            </td>
            <td class="px-md py-sm text-[#333333]">{{ row.result }}</td>
            <td class="px-md py-sm text-[#666666]">{{ row.blocker }}</td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>
  </section>
</template>

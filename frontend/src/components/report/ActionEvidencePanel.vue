<script setup>
import { computed } from 'vue'

const props = defineProps({
  evidence: { type: Object, default: () => ({}) }
})

const validatedActions = computed(() => props.evidence?.validated_actions || [])
const businessActions = computed(() => props.evidence?.business_actions || [])
const possibleJourneys = computed(() => props.evidence?.possible_journeys || [])

const statusLabel = (value) => {
  const text = String(value || '').trim()
  if (!text) return ''
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`
}

const statusClasses = (value) => {
  switch (String(value || '').toLowerCase()) {
    case 'success':
      return 'border-[#1f7a36] text-[#1f7a36]'
    case 'partial':
      return 'border-[#c97a00] text-[#c97a00]'
    default:
      return 'border-[#cccccc] text-[#666666]'
  }
}

const confidenceClasses = (value) => {
  switch (String(value || '').toLowerCase()) {
    case 'high':
      return 'border-[#1f7a36] text-[#1f7a36]'
    case 'medium':
      return 'border-[#b36b00] text-[#b36b00]'
    default:
      return 'border-[#888888] text-[#666666]'
  }
}
</script>

<template>
  <section class="space-y-lg">
    <section class="space-y-sm">
      <div>
        <p class="text-label-md text-[#888888]">Validated evidence</p>
        <h2 class="mt-xs text-body-lg font-medium normal-case text-[#111111]">
          What the agent actually did
        </h2>
      </div>

      <div
        v-if="validatedActions.length"
        class="grid gap-sm md:grid-cols-2"
      >
        <article
          v-for="item in validatedActions"
          :key="item.id || item.title"
          class="border border-[#eeeeee] bg-white p-md"
        >
          <div class="flex flex-wrap items-center justify-between gap-xs">
            <p class="text-body-md font-medium normal-case text-[#111111]">{{ item.title }}</p>
            <span
              class="border px-xs py-[1px] text-label-md uppercase tracking-[0.12em]"
              :class="statusClasses(item.status)"
            >
              {{ statusLabel(item.status) }}
            </span>
          </div>
          <p
            v-if="item.goal"
            class="mt-xs text-body-md normal-case text-[#555555]"
          >
            {{ item.goal }}
          </p>
          <p
            v-if="item.supporting_detail || item.result"
            class="mt-sm text-body-md normal-case text-[#111111]"
          >
            {{ item.supporting_detail || item.result }}
          </p>
          <p
            v-if="item.blocker && item.blocker !== '—'"
            class="mt-xs text-body-md normal-case text-[#a14b00]"
          >
            Blocker: {{ item.blocker }}
          </p>
        </article>
      </div>

      <p
        v-else
        class="border border-[#eeeeee] bg-[#fafafa] p-md text-body-md normal-case text-[#888888]"
      >
        The browser run did not validate a completed action path yet.
      </p>
    </section>

    <section
      v-if="businessActions.length"
      class="space-y-sm"
    >
      <div>
        <p class="text-label-md text-[#888888]">High-confidence inference</p>
        <h2 class="mt-xs text-body-lg font-medium normal-case text-[#111111]">
              Most important business actions detected
        </h2>
      </div>

      <div class="grid gap-sm md:grid-cols-2">
        <article
          v-for="item in businessActions"
          :key="item.id || item.title"
          class="border border-[#eeeeee] bg-[#fafafa] p-md"
        >
          <div class="flex flex-wrap items-center gap-xs">
            <p class="text-body-md font-medium normal-case text-[#111111]">{{ item.title }}</p>
            <span
              class="border px-xs py-[1px] text-label-md uppercase tracking-[0.12em]"
              :class="confidenceClasses(item.confidence)"
            >
              {{ statusLabel(item.confidence) }} confidence
            </span>
            <span
              v-if="item.status"
              class="border px-xs py-[1px] text-label-md uppercase tracking-[0.12em]"
              :class="statusClasses(item.status)"
            >
              {{ statusLabel(item.status) }}
            </span>
          </div>
          <p
            v-if="item.goal"
            class="mt-xs text-body-md normal-case text-[#444444]"
          >
            {{ item.goal }}
          </p>
          <p class="mt-sm text-body-md normal-case text-[#666666]">{{ item.basis_inline }}</p>
          <p
            v-if="item.result"
            class="mt-sm text-body-md normal-case text-[#111111]"
          >
            {{ item.result }}
          </p>
          <p
            v-if="item.blocker"
            class="mt-xs text-body-md normal-case text-[#a14b00]"
          >
            Blocker: {{ item.blocker }}
          </p>
        </article>
      </div>
    </section>

    <details
      v-if="possibleJourneys.length"
      class="group border border-[#e5e5e5] bg-white"
    >
      <summary class="flex cursor-pointer list-none items-center justify-between gap-sm px-md py-sm">
        <div>
          <p class="text-body-md font-medium normal-case text-[#111111]">
            Possible journeys we inferred
          </p>
          <p class="text-body-md normal-case text-[#666666]">
            Lower-confidence guesses from crawl structure. These are not validated actions.
          </p>
        </div>
        <span class="text-label-md text-[#888888]">{{ possibleJourneys.length }} item(s)</span>
      </summary>

      <div class="grid gap-sm border-t border-[#eeeeee] p-md md:grid-cols-2">
        <article
          v-for="item in possibleJourneys"
          :key="item.id || item.title"
          class="border border-[#eeeeee] bg-[#fafafa] p-md"
        >
          <div class="flex flex-wrap items-center gap-xs">
            <p class="text-body-md font-medium normal-case text-[#111111]">{{ item.title }}</p>
            <span
              class="border px-xs py-[1px] text-label-md uppercase tracking-[0.12em]"
              :class="confidenceClasses(item.confidence)"
            >
              {{ statusLabel(item.confidence) }} confidence
            </span>
            <span
              v-if="item.status"
              class="border px-xs py-[1px] text-label-md uppercase tracking-[0.12em]"
              :class="statusClasses(item.status)"
            >
              {{ statusLabel(item.status) }}
            </span>
          </div>
          <p
            v-if="item.goal"
            class="mt-xs text-body-md normal-case text-[#444444]"
          >
            {{ item.goal }}
          </p>
          <p class="mt-sm text-body-md normal-case text-[#666666]">{{ item.basis_inline }}</p>
          <p
            v-if="item.result"
            class="mt-sm text-body-md normal-case text-[#111111]"
          >
            {{ item.result }}
          </p>
          <p
            v-if="item.blocker"
            class="mt-xs text-body-md normal-case text-[#a14b00]"
          >
            Blocker: {{ item.blocker }}
          </p>
        </article>
      </div>
    </details>
  </section>
</template>

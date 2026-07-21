<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  message: { type: String, default: 'Working…' },
  notice: { type: String, default: '' },
  loadingInsights: { type: Array, default: () => [] },
  phase: { type: String, default: 'crawl' },
  progressPct: { type: Number, default: 0 },
  activityLog: { type: Array, default: () => [] },
  startedAt: { type: String, default: '' },
  canCancel: { type: Boolean, default: false },
  steps: {
    type: Array,
    default: () => [
      { phase: 'crawl', label: '1. crawl site' },
      { phase: 'explore', label: '2. agent explore' }
    ]
  }
})

const emit = defineEmits(['cancel'])

const showCloseHint = ref(false)
const closeHintDismissed = ref(false)
const currentInsight = ref('')
let closeHintTimer = null
let insightTimer = null

const pct = computed(() => Math.max(0, Math.min(100, props.progressPct || 0)))
const displayedInsight = computed(() => props.notice || currentInsight.value || '')

function clearCloseHintTimer() {
  if (closeHintTimer) clearTimeout(closeHintTimer)
  closeHintTimer = null
}

function clearInsightTimer() {
  if (insightTimer) clearTimeout(insightTimer)
  insightTimer = null
}

function startInsightRotation() {
  clearInsightTimer()
  const insights = props.loadingInsights || []
  if (!insights.length) {
    currentInsight.value = ''
    return
  }

  let index = Math.floor(Math.random() * insights.length)

  const showNextInsight = () => {
    currentInsight.value = insights[index] || ''
    index = (index + 1) % insights.length
    insightTimer = setTimeout(showNextInsight, 10_000 + Math.floor(Math.random() * 5_000))
  }

  showNextInsight()
}

watch(
  () => props.visible,
  (on) => {
    clearCloseHintTimer()
    clearInsightTimer()
    showCloseHint.value = false
    if (on) {
      startInsightRotation()
      closeHintDismissed.value = false
      closeHintTimer = setTimeout(() => {
        if (!closeHintDismissed.value) showCloseHint.value = true
      }, 7000)
    } else {
      currentInsight.value = ''
    }
  },
  { immediate: true }
)

watch(
  () => props.loadingInsights,
  () => {
    if (props.visible) startInsightRotation()
  }
)

onBeforeUnmount(() => {
  clearCloseHintTimer()
  clearInsightTimer()
})
</script>

<template>
  <div
    v-if="visible"
    class="fixed inset-x-0 bottom-0 top-14 z-[100] flex flex-col items-center justify-center bg-white/90 backdrop-blur-sm px-gutter md:top-16"
  >
    <div class="w-full max-w-[560px] space-y-lg text-center" role="status" aria-live="polite">
      <div class="space-y-md">
        <div class="flex justify-center">
          <div class="h-7 w-7 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>

        <div class="space-y-xxs">
          <p class="text-title-sm font-medium text-primary">{{ message }}</p>
          <p class="text-body-md text-secondary">Usually a few minutes for crawl + explore</p>
        </div>
      </div>

      <div class="space-y-xs text-left">
        <div class="flex items-baseline justify-between gap-md">
          <span class="text-label-md text-secondary">Progress</span>
          <span class="text-body-md font-medium text-primary">{{ pct }}% complete</span>
        </div>
        <div class="h-2.5 w-full overflow-hidden rounded-full bg-surface-container-low">
          <div class="h-full bg-primary transition-all duration-500" :style="{ width: `${pct}%` }" />
        </div>
      </div>

      <div
        v-if="displayedInsight"
        class="w-full border border-outline-variant bg-white px-md py-sm text-center"
      >
        <p class="text-body-md leading-relaxed text-primary">{{ displayedInsight }}</p>
      </div>

      <div
        v-if="showCloseHint"
        class="flex w-full items-start justify-between gap-md bg-surface-container-lowest px-md py-sm text-left text-body-md leading-snug text-secondary"
      >
        <span>
          You can leave this page. Progress stays under Runs — refresh there when the study finishes.
        </span>
        <button
          type="button"
          class="shrink-0 bg-transparent p-0 text-body-lg leading-none text-secondary transition-colors hover:bg-transparent hover:text-primary"
          aria-label="Dismiss hint"
          @click="closeHintDismissed = true; showCloseHint = false"
        >
          ×
        </button>
      </div>

      <button
        v-if="canCancel"
        type="button"
        class="oi-home-btn-ghost mx-auto border border-outline-variant px-md py-xs text-body-md"
        @click="emit('cancel')"
      >
        Stop study
      </button>
    </div>
  </div>
</template>

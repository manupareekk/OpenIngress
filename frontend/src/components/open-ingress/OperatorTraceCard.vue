<script setup>
import { computed } from 'vue'

const props = defineProps({
  traces: { type: Array, default: () => [] },
  screenshotObjectUrls: { type: Object, default: () => ({}) }
})

const screenshotRefs = (event) => {
  const direct = event?.metadata?.screenshots || {}
  return [
    { kind: 'viewport', shot: direct.viewport },
    { kind: 'after click', shot: direct.after_click },
    { kind: 'before', shot: direct.before },
    { kind: 'after', shot: direct.after }
  ].filter((item) => item.shot?.url)
}

const traceItems = computed(() => {
  const items = []
  for (const trace of props.traces) {
    for (const event of (trace.events || []).slice(0, 12)) {
      for (const { kind, shot } of screenshotRefs(event)) {
        items.push({
          id: `${trace.sessionId}-${event.step}-${event.action}-${kind}`,
          step: event.step,
          action: event.action || event.event_type,
          name: event.element_name || '',
          detail: event.url || event.metadata?.path || event.reasoning_summary || '',
          image: props.screenshotObjectUrls[shot.url] || null,
          label: shot.label || `Step ${event.step}`,
          kind
        })
      }
    }
  }
  return items
})
</script>

<template>
  <section v-if="traceItems.length" class="space-y-md">
    <div class="px-xs space-y-xs">
      <h3 class="text-headline-md font-medium">Playwright crawl screenshots</h3>
      <p class="text-body-md text-secondary">
        Stored screenshots captured during the live crawl and click path.
      </p>
    </div>
    <div class="oi-masonry-trace">
      <article
        v-for="(item, i) in traceItems"
        :key="item.id"
        class="oi-block-card overflow-hidden mb-gutter hover:bg-[#f0f0f0]"
      >
        <div v-if="item.image" class="border-b border-outline-variant">
          <img :src="item.image" :alt="item.label" class="w-full h-auto" loading="lazy" />
        </div>
        <div v-else class="aspect-video bg-surface-container-low border-b border-outline-variant flex items-center justify-center">
          <span class="material-symbols-outlined text-secondary text-[32px]">screenshot</span>
        </div>
        <div class="p-sm">
          <div class="flex items-center gap-xs mb-xs">
            <span class="w-2 h-2 rounded-full bg-primary" />
            <span class="text-label-md font-bold">STEP {{ String(i + 1).padStart(2, '0') }}</span>
            <span class="text-label-md uppercase tracking-[0.08em] text-secondary">{{ item.kind }}</span>
          </div>
          <div class="text-body-md font-bold">{{ item.action }}<span v-if="item.name"> · {{ item.name }}</span></div>
          <div class="text-secondary text-label-md truncate">{{ item.detail }}</div>
        </div>
      </article>
    </div>
  </section>
  <p v-else class="text-body-md text-secondary border border-outline-variant p-md rounded-lg">
    No trace screenshots were stored for this run.
  </p>
</template>

<script setup>
const props = defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  hint: { type: String, default: '' }
})
</script>

<template>
  <section class="oi-dash-card oi-dash-card-pad">
    <div class="flex items-start justify-between gap-sm">
      <div class="min-w-0">
        <div class="oi-dash-stat-label">{{ props.label }}</div>
        <div class="oi-dash-stat-value">{{ props.value }}</div>
      </div>
      <div v-if="props.hint" class="oi-dash-pill">{{ props.hint }}</div>
    </div>
    <slot />
  </section>
</template>


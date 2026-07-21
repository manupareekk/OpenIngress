<script setup>
const props = defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' }
})
</script>

<template>
  <section class="oi-dash-card">
    <div v-if="props.title || props.subtitle" class="oi-dash-card-pad border-b" style="border-color: var(--oi-dash-border);">
      <div class="flex items-start justify-between gap-sm">
        <div class="min-w-0">
          <div class="text-body-md font-medium">{{ props.title }}</div>
          <div v-if="props.subtitle" class="mt-xs text-body-md oi-dash-muted">{{ props.subtitle }}</div>
        </div>
        <slot name="actions" />
      </div>
    </div>
    <div class="oi-dash-card-pad">
      <slot />
    </div>
  </section>
</template>


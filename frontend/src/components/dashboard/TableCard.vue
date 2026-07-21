<script setup>
import Card from './Card.vue'

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' }
})
</script>

<template>
  <Card :title="props.title" :subtitle="props.subtitle">
    <div class="-mx-sm overflow-x-auto">
      <div class="min-w-[720px] px-sm">
        <table class="oi-dash-table">
          <slot />
        </table>
      </div>
    </div>
  </Card>
</template>


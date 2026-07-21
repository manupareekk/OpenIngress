<script setup>
import OpenIngressMark from './OpenIngressMark.vue'
import OpenIngressBrand from './OpenIngressBrand.vue'

defineProps({
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg', 'xl'].includes(v)
  },
  showWordmark: {
    type: Boolean,
    default: true
  }
})
</script>

<template>
  <span class="oi-logo inline-flex min-w-0 items-center gap-2">
    <OpenIngressMark :size="size" />
    <OpenIngressBrand v-if="showWordmark" class="text-body-md font-medium leading-none" />
  </span>
</template>

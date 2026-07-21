<script setup>
defineProps({
  title: { type: String, required: true },
  meta: { type: String, default: '' }
})
</script>

<template>
  <details class="group border border-[#e5e5e5] bg-white">
    <summary class="cursor-pointer list-none px-md py-sm md:px-lg [&::-webkit-details-marker]:hidden">
      <div class="flex items-center justify-between gap-sm">
        <div class="flex min-w-0 items-center gap-sm">
          <span
            class="inline-flex shrink-0 text-[12px] leading-none text-[#888888] transition-transform duration-150 group-open:rotate-90"
            aria-hidden="true"
          >
            ▸
          </span>
          <span class="text-body-lg font-medium text-[#111111]">{{ title }}</span>
        </div>
        <span v-if="meta" class="shrink-0 text-body-md text-[#888888]">{{ meta }}</span>
      </div>
    </summary>
    <div class="border-t border-[#eeeeee]">
      <slot />
    </div>
  </details>
</template>

<script setup>
const props = defineProps({
  name: { type: String, required: true }
})

const size = 20
</script>

<template>
  <svg
    v-if="props.name === 'overview'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M4 13.5v6.5h6.5v-6.5H4z" />
    <path d="M13.5 4h6.5v6.5h-6.5V4z" />
    <path d="M13.5 13.5h6.5V20h-6.5v-6.5z" />
    <path d="M4 4h6.5v6.5H4V4z" />
  </svg>

  <svg
    v-else-if="props.name === 'runs'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M4 6h16" />
    <path d="M4 12h16" />
    <path d="M4 18h12" />
  </svg>

  <svg
    v-else-if="props.name === 'blockers'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
    <path d="M10 3h4l7 7v4l-7 7h-4l-7-7v-4l7-7z" />
  </svg>

  <svg
    v-else-if="props.name === 'analytics'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M4 19V5" />
    <path d="M4 19h16" />
    <path d="M7 15l4-5 4 3 5-7" />
  </svg>

  <svg
    v-else-if="props.name === 'account'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" />
    <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
  </svg>

  <svg
    v-else-if="props.name === 'fixes'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M12 2l1.6 5 5 .1-4 3 1.5 5-4.1-2.8L7.9 15l1.5-5-4-3 5-.1L12 2z" />
    <path d="M5 21h14" />
  </svg>

  <svg
    v-else-if="props.name === 'plus'"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M12 5v14" />
    <path d="M5 12h14" />
  </svg>

  <span v-else aria-hidden="true" />
</template>

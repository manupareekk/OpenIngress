<script setup>
defineProps({
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg', 'xl'].includes(v)
  }
})
</script>

<template>
  <svg
    class="oi-mark"
    :class="{
      'oi-mark--sm': size === 'sm',
      'oi-mark--md': size === 'md',
      'oi-mark--lg': size === 'lg',
      'oi-mark--xl': size === 'xl'
    }"
    viewBox="0 0 32 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
    focusable="false"
  >
    <!-- left portal frame -->
    <path
      d="M1.5 1.5V14.5M1.5 1.5H7.5M1.5 14.5H7.5"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="square"
    />
    <!-- right portal frame -->
    <path
      d="M30.5 1.5V14.5M30.5 1.5H24.5M30.5 14.5H24.5"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="square"
    />
    <!-- ingress arrow — shaft meets chevron at tip; butt caps avoid the square overshoot -->
    <path
      d="M12 8H20 M17.5 5.5L20 8L17.5 10.5"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="butt"
      stroke-linejoin="miter"
    />
  </svg>
</template>

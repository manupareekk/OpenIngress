<script setup>
import { githubUrl } from '../../config/siteLinks'
import LoginProviderIcon from './LoginProviderIcon.vue'

defineProps({
  showLabel: { type: Boolean, default: false }
})
</script>

<template>
  <a
    :href="githubUrl"
    class="inline-flex items-center gap-xs text-[#111111] transition-colors hover:text-secondary"
    target="_blank"
    rel="noreferrer"
    aria-label="OpenIngress on GitHub"
  >
    <LoginProviderIcon provider="github" />
    <span v-if="showLabel">GitHub</span>
  </a>
</template>

<template>
  <div class="ap-shell" :class="{ 'ap-shell--wizard': wizard }">
    <header class="ap-shell__topbar">
      <div class="ap-shell__brand-wrap">
        <router-link to="/" class="ap-shell__brand normal-case">OpenIngress</router-link>
        <span class="ap-shell__product">Agent operability</span>
      </div>
      <nav v-if="!wizard" class="ap-shell__nav" aria-label="Main">
        <router-link to="/" class="ap-shell__nav-link" :class="{ active: activeNav === 'dashboard' }">
          Runs
        </router-link>
      </nav>
      <div v-if="!wizard" class="ap-shell__meta">
        <slot name="status" />
      </div>
    </header>

    <div v-if="wizard && $slots.wizardNav" class="ap-shell__wizard-bar">
      <router-link to="/" class="ap-shell__back-link">← Runs</router-link>
      <nav class="ap-shell__wizard-nav" aria-label="Run steps">
        <slot name="wizardNav" />
      </nav>
      <div class="ap-shell__wizard-meta">
        <slot name="status" />
      </div>
    </div>

    <main class="ap-shell__main" :class="{ 'ap-shell__main--wizard': wizard }">
      <slot />
    </main>
  </div>
</template>

<script setup>
defineProps({
  activeNav: {
    type: String,
    default: 'dashboard'
  },
  wizard: {
    type: Boolean,
    default: false
  }
})
</script>

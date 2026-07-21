<template>
  <div class="decision-card ingress-summary">
    <div>
      <span class="status-label">Operability</span>
      <h3>{{ headline }}</h3>
      <p>{{ detail }}</p>
    </div>
    <slot name="action" />
  </div>
</template>

<script setup>
defineProps({
  headline: { type: String, required: true },
  detail: { type: String, default: '' }
})
</script>

<style scoped>
.ingress-summary {
  border: 1px solid #111;
  padding: 16px;
  margin-bottom: 16px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  background: #111;
  color: #fffaf0;
}

.status-label {
  display: block;
  font-size: 12px;
  text-transform: uppercase;
  color: #5eead4;
  margin-bottom: 8px;
}

.ingress-summary h3 {
  margin: 0 0 8px;
  text-transform: none;
  letter-spacing: 0;
}

.ingress-summary p {
  margin: 0;
  color: #d1fae5;
  line-height: 1.45;
}
</style>

<template>
  <div class="wizard-step-nav">
    <label class="wizard-step-nav__mobile-label">
      <span class="sr-only">Jump to step</span>
      <select
        class="wizard-step-nav__select"
        :value="activeStep"
        :disabled="locked"
        @change="onSelectChange"
      >
        <option v-for="step in steps" :key="step.id" :value="step.id" :disabled="!canGo(step.id)">
          {{ step.label }}
        </option>
      </select>
    </label>
    <nav class="wizard-step-nav__tabs" aria-label="Simulation steps">
      <button
        v-for="step in steps"
        :key="step.id"
        type="button"
        class="ap-shell__step-btn"
        :class="{
          active: activeStep === step.id,
          complete: complete(step.id),
          'ap-shell__step-btn--disabled': !canGo(step.id)
        }"
        :disabled="locked || !canGo(step.id)"
        :title="!canGo(step.id) ? 'Complete earlier steps first' : step.label"
        @click="$emit('go', step.id)"
      >
        {{ step.label }}
      </button>
    </nav>
  </div>
</template>

<script setup>
const props = defineProps({
  steps: {
    type: Array,
    required: true
  },
  activeStep: {
    type: String,
    required: true
  },
  locked: {
    type: Boolean,
    default: false
  },
  canGo: {
    type: Function,
    required: true
  },
  complete: {
    type: Function,
    required: true
  }
})

const emit = defineEmits(['go'])

const onSelectChange = (event) => {
  const value = event.target?.value
  if (value && props.canGo(value)) emit('go', value)
}
</script>

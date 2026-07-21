<script setup>
import { ref } from 'vue'

const props = defineProps({
  reportMd: { type: String, default: '' }
})

const copied = ref(false)
const toast = ref('')

async function copyReport() {
  if (!props.reportMd) return
  try {
    await navigator.clipboard.writeText(props.reportMd)
    copied.value = true
    toast.value = 'Report copied'
    setTimeout(() => {
      copied.value = false
      toast.value = ''
    }, 2500)
  } catch {
    toast.value = 'Copy failed — select text manually'
  }
}
</script>

<template>
  <section class="border border-[#eeeeee] bg-white p-md space-y-sm">
    <div class="space-y-xs">
      <h3 class="text-body-md font-medium text-[#111111]">Report export</h3>
      <p class="text-body-md normal-case leading-relaxed text-[#666666]">
        Downloadable markdown of this study for notes or sharing with your team.
      </p>
    </div>
    <button type="button" class="oi-dash-btn oi-dash-btn-ghost" :disabled="!reportMd" @click="copyReport">
      {{ copied ? 'Copied' : 'Copy report markdown' }}
    </button>
    <p v-if="toast" class="text-body-md text-[#666666]">{{ toast }}</p>
  </section>
</template>

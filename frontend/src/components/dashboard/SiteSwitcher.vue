<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const props = defineProps({
  sites: { type: Array, default: () => [] }, // [{ key, label }]
  selected: { type: String, default: '' } // '' means all
})

const route = useRoute()
const router = useRouter()

const open = ref(false)
const query = ref('')
const panelRef = ref(null)
const searchRef = ref(null)

const displayLabel = computed(() => {
  if (!Array.isArray(props.sites) || !props.sites.length) return 'No site selected'
  const key = String(props.selected || '')
  if (!key) return 'All sites'
  return props.sites.find((s) => s.key === key)?.label || 'Site'
})

const filtered = computed(() => {
  const q = String(query.value || '').trim().toLowerCase()
  const sites = Array.isArray(props.sites) ? props.sites : []
  if (!q) return sites
  return sites.filter((s) => String(s.label || '').toLowerCase().includes(q))
})

function setSite(key) {
  const next = key || ''
  const nextQuery = { ...route.query }
  if (next) nextQuery.site = next
  else delete nextQuery.site
  router.replace({ path: route.path, query: nextQuery })
  open.value = false
}

function onKeydown(e) {
  if (e.key === 'Escape') open.value = false
}

function onDocPointerDown(e) {
  if (!open.value) return
  const el = panelRef.value
  if (!el) return
  if (el.contains(e.target)) return
  open.value = false
}

watch(open, async (v) => {
  if (!v) return
  query.value = ''
  await nextTick()
  searchRef.value?.focus?.()
})

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('pointerdown', onDocPointerDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('pointerdown', onDocPointerDown)
})
</script>

<template>
  <div class="oi-dash-site-switch" ref="panelRef">
    <button
      type="button"
      class="oi-dash-site-btn"
      :class="{ 'is-empty': !sites || !sites.length }"
      :disabled="!sites || !sites.length"
      @click="open = !open"
      :aria-expanded="open ? 'true' : 'false'"
    >
      <span class="truncate">{{ displayLabel }}</span>
      <span v-if="sites && sites.length" aria-hidden="true" class="oi-dash-muted">⌄</span>
    </button>

    <div v-if="open && sites && sites.length" class="oi-dash-site-panel" role="dialog" aria-label="Select site">
      <div class="oi-dash-site-panel-head">
        <div class="oi-dash-site-search">
          <span class="oi-dash-muted" aria-hidden="true">⌕</span>
          <input ref="searchRef" v-model="query" placeholder="Find site…" />
        </div>
      </div>

      <div class="oi-dash-site-list" role="listbox" :aria-activedescendant="selected ? `site-${selected}` : 'site-all'">
        <button
          v-if="!query"
          id="site-all"
          type="button"
          class="oi-dash-site-item"
          :class="{ 'is-active': !selected }"
          @click="setSite('')"
        >
          <span class="oi-dash-icon" aria-hidden="true">
            <span
              class="inline-flex h-4 w-4 items-center justify-center rounded-full"
              style="background: var(--oi-dash-surface-2); border: 1px solid var(--oi-dash-border); font-size: 10px;"
            >
              *
            </span>
          </span>
          <span class="truncate">All sites</span>
        </button>

        <button
          v-for="s in filtered"
          :id="`site-${s.key}`"
          :key="s.key"
          type="button"
          class="oi-dash-site-item"
          :class="{ 'is-active': s.key === selected }"
          @click="setSite(s.key)"
        >
          <span class="oi-dash-icon" aria-hidden="true">
            <span
              class="inline-flex h-4 w-4 items-center justify-center rounded-full"
              style="background: var(--oi-dash-surface-2); border: 1px solid var(--oi-dash-border); font-size: 10px;"
            >
              {{ String(s.label || '?').slice(0, 1).toUpperCase() }}
            </span>
          </span>
          <span class="truncate">{{ s.label }}</span>
        </button>

        <div v-if="!filtered.length" class="oi-dash-site-empty oi-dash-muted">No matches</div>
      </div>
    </div>
  </div>
</template>

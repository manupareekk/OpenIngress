<template>
  <div class="navigation-card">
    <div class="variant-header">
      <h3>Agent navigation map</h3>
      <button
        v-if="showAnalyzeButton"
        type="button"
        class="ghost-btn"
        :disabled="disabled || analyzing"
        :data-tooltip="analyzeTooltip"
        :title="analyzeTooltip"
        @click="$emit('analyze')"
      >
        {{ analyzing ? 'Analyzing…' : 'Analyze map' }}
      </button>
    </div>

    <p v-if="!variants.length" class="limit-note">
      {{ emptyText }}
    </p>

    <div v-else class="graph-review">
      <article v-for="variant in variants" :key="variant.id" class="graph-variant">
        <div class="flow-result-header">
          <strong>{{ itemTitle(variant) }}</strong>
          <span>{{ quality(variant).actions || 0 }} actions / {{ quality(variant).issues || 0 }} issues</span>
        </div>
        <div class="graph-quality">
          <small>Coverage: {{ formatCoverage(quality(variant).static_coverage) }}</small>
          <small>Goal reachable: {{ quality(variant).goal_reachable ? 'yes' : 'no' }}</small>
          <small>Pages: {{ quality(variant).pages || 0 }}</small>
        </div>
        <div v-if="issueLines(variant).length" class="graph-issues">
          <small v-for="(line, index) in issueLines(variant)" :key="`${variant.id}-issue-${index}`">{{ line }}</small>
        </div>
        <p v-else-if="(quality(variant).actions || 0) === 0" class="limit-note">
          No actions detected — page HTML may be empty or loaded only via JavaScript.
        </p>
      </article>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  variants: {
    type: Array,
    default: () => []
  },
  analyzing: {
    type: Boolean,
    default: false
  },
  disabled: {
    type: Boolean,
    default: false
  },
  showAnalyzeButton: {
    type: Boolean,
    default: true
  },
  itemLabel: {
    type: String,
    default: 'Snapshot'
  },
  emptyText: {
    type: String,
    default: 'Import a URL to see which actions agents can resolve vs blocked paths.'
  },
  analyzeTooltip: {
    type: String,
    default: 'Scan imported pages for links, buttons, and forms operators can follow.'
  }
})

defineEmits(['analyze'])

const quality = (variant) => variant?.navigation_graph?.quality || {}

const itemTitle = (variant) => {
  if (['site', 'snapshot'].includes(props.itemLabel.toLowerCase())) return variant.name || 'Site'
  return `${props.itemLabel} ${variant.id}${variant.name ? `: ${variant.name}` : ''}`
}

const formatCoverage = (value) => {
  const numeric = Number(value ?? 1)
  if (!Number.isFinite(numeric)) return '—'
  return `${Math.round(numeric * 100)}%`
}

const issueLines = (variant) => {
  const issues = variant?.navigation_graph?.issues
  if (!Array.isArray(issues) || !issues.length) return []
  return issues.slice(0, 4).map((issue) => {
    const page = issue.page_id ? `[${issue.page_id}] ` : ''
    return `${page}${issue.message || issue.code || 'Navigation issue'}`
  })
}
</script>

<style scoped>
.navigation-card {
  border: 1px solid #eadfce;
  border-radius: 12px;
  padding: 16px;
  background: #fffdf8;
}

.graph-review {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}

.graph-variant {
  border-top: 1px solid #eadfce;
  padding-top: 12px;
}

.graph-variant:first-child {
  border-top: 0;
  padding-top: 0;
}

.graph-quality,
.graph-issues {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.graph-quality {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.graph-issues small {
  color: #7c2d12;
  line-height: 1.35;
}

.limit-note {
  margin: 8px 0 0;
  color: #6b5c4d;
  font-size: 13px;
  line-height: 1.4;
}
</style>

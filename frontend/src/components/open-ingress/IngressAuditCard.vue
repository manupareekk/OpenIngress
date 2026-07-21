<template>
  <div class="audit-card">
    <div class="audit-card__hero">
      <span class="audit-card__eyebrow">Agent experience score</span>
      <h2>{{ readinessScore }} / 100</h2>
      <p class="audit-card__cta">
        {{ audit?.readiness?.methodology || audit?.audit_focus || 'Agent readiness for accessibility-tree browsers.' }}
      </p>
    </div>

    <p v-if="audit?.exploration_summary?.mode" class="audit-card__policy">
      Exploration: {{ audit.exploration_summary.mode }}
      <span v-if="audit.exploration_summary.llm_enabled"> · LLM policy</span>
    </p>

    <div v-if="audit?.readiness" class="dashboard-stats">
      <article class="dashboard-stat">
        <span>Catalog (crawl)</span>
        <strong>{{ audit.readiness.crawl_completeness_percent }}%</strong>
      </article>
      <article class="dashboard-stat">
        <span>Aria match</span>
        <strong>{{ audit.readiness.aria_match_percent ?? '—' }}%</strong>
      </article>
      <article class="dashboard-stat">
        <span>Activated</span>
        <strong>{{ audit.readiness.activation_percent ?? '—' }}%</strong>
      </article>
      <article v-if="audit.universe_totals" class="dashboard-stat">
        <span>Actions in universe</span>
        <strong>{{ audit.universe_totals.actions }}</strong>
      </article>
    </div>

    <div v-if="audit?.coverage" class="dashboard-stats">
      <article class="dashboard-stat">
        <span>Accessibility</span>
        <strong>{{ audit.agent_accessibility_score ?? audit.coverage.action_accessibility_percent }}%</strong>
      </article>
      <article class="dashboard-stat">
        <span>Speed</span>
        <strong>{{ audit.agent_speed_score ?? audit.speed_summary?.score ?? '—' }}%</strong>
      </article>
      <article class="dashboard-stat">
        <span>Off-site links</span>
        <strong>{{ audit.coverage.external_actions ?? '—' }}</strong>
      </article>
      <article v-if="audit.coverage.on_site_only_percent !== undefined" class="dashboard-stat">
        <span>On-site only</span>
        <strong>{{ audit.coverage.on_site_only_percent }}%</strong>
      </article>
    </div>

    <div v-if="audit?.speed_summary" class="audit-card__section">
      <h3>Speed signals</h3>
      <div class="speed-grid">
        <span>{{ formatBytes(audit.speed_summary.html_bytes) }} HTML</span>
        <span>{{ audit.speed_summary.script_count || 0 }} scripts</span>
        <span>{{ audit.speed_summary.stylesheet_count || 0 }} stylesheets</span>
        <span>{{ audit.speed_summary.image_count || 0 }} images</span>
      </div>
    </div>

    <div v-if="audit?.rationale?.length" class="audit-card__section">
      <h3>Audit summary</h3>
      <ul>
        <li v-for="(line, i) in audit.rationale" :key="i">{{ line }}</li>
      </ul>
    </div>

    <div v-if="audit?.recommendations?.length" class="audit-card__section audit-card__fixes">
      <h3>What you should do</h3>
      <ol>
        <li v-for="(rec, i) in audit.recommendations" :key="i">{{ rec }}</li>
      </ol>
    </div>

    <details v-if="audit?.top_actions?.length" class="audit-card__section">
      <summary>Top detected actions</summary>
      <ul>
        <li v-for="(action, i) in audit.top_actions" :key="i">
          {{ action.label }} ({{ Math.round((action.score || 0) * 100) }}%) — {{ action.reason }}
        </li>
      </ul>
    </details>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  audit: {
    type: Object,
    default: () => ({})
  }
})

const readinessScore = computed(() => {
  const readiness = props.audit?.readiness?.readiness_score
  if (readiness !== undefined && readiness !== null) return Math.round(readiness)
  const score = props.audit?.overall_score
  if (score !== undefined && score !== null) return Math.round(score)
  return '—'
})

const formatBytes = (value) => {
  const bytes = Number(value || 0)
  if (!bytes) return '0 KB'
  if (bytes < 1_000_000) return `${Math.round(bytes / 1000)} KB`
  return `${(bytes / 1_000_000).toFixed(1)} MB`
}
</script>

<style scoped>
.audit-card {
  border: 2px solid #1c1b1c;
  background: #fff;
  box-shadow: 6px 6px 0 #1c1b1c;
  margin-bottom: 20px;
}

.audit-card__hero {
  background: #111;
  color: #f8fafc;
  padding: 20px 22px;
}

.audit-card__eyebrow {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #5eead4;
}

.audit-card__hero h2 {
  margin: 8px 0;
  font-size: 1.35rem;
  line-height: 1.35;
  text-transform: none;
  letter-spacing: 0;
}

.audit-card__cta {
  margin: 0;
  color: #cbd5e1;
  font-size: 0.9rem;
}

.audit-card__policy {
  margin: 0;
  padding: 10px 22px 0;
  font-size: 12px;
  color: #64748b;
}

.audit-card__section {
  padding: 16px 22px;
  border-top: 1px solid #e2e8f0;
}

.audit-card__fixes ol {
  margin: 0;
  padding-left: 1.2rem;
}

.audit-card__fixes li {
  margin-bottom: 0.65rem;
  line-height: 1.45;
}

.audit-card__section ul {
  margin: 0;
  padding-left: 1.2rem;
}

.speed-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.speed-grid span {
  border: 1px solid #cbd5e1;
  padding: 6px 8px;
  font-family: var(--ap-font-mono, monospace);
  font-size: 12px;
}

summary {
  cursor: pointer;
  font-weight: 600;
}
</style>

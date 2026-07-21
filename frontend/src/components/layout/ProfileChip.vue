<script setup>
import { computed } from 'vue'
import { useAuth } from '../../composables/useAuth'

const { state, creditBalance } = useAuth()

const displayEmail = computed(() => {
  const email = state.user?.email
  if (!email) return 'Account'
  const [local, domain] = email.split('@')
  if (!domain || local.length <= 14) return email
  return `${local.slice(0, 12)}…@${domain}`
})

const creditLabel = computed(() => {
  if (state.billingDisabled || creditBalance.value == null) return 'Beta'
  if (state.isEnterprise) return 'Enterprise'
  return `${creditBalance.value} cr`
})

const initials = computed(() => {
  const src = state.user?.name || state.user?.email || '?'
  const parts = src.split(/[\s@.]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return src.slice(0, 2).toUpperCase()
})
</script>

<template>
  <router-link to="/app/account" class="oi-profile-chip" :title="state.user?.email || 'Account'">
    <img
      v-if="state.user?.avatar"
      :src="state.user.avatar"
      alt=""
      class="oi-profile-chip__avatar"
      referrerpolicy="no-referrer"
    />
    <span v-else class="oi-profile-chip__avatar oi-profile-chip__avatar--initials">{{ initials }}</span>
    <span class="hidden min-w-0 sm:inline">
      <span class="oi-profile-chip__email">{{ displayEmail }}</span>
      <span class="oi-profile-chip__credits">{{ creditLabel }}</span>
    </span>
  </router-link>
</template>

<style scoped>
.oi-profile-chip {
  display: inline-flex;
  max-width: 200px;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: inherit;
}

.oi-profile-chip:hover .oi-profile-chip__email {
  color: #666666;
}

.oi-profile-chip__avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  border: 1px solid #e5e5e5;
}

.oi-profile-chip__avatar--initials {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #111111;
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
}

.oi-profile-chip__email {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: #111111;
  line-height: 1.2;
}

.oi-profile-chip__credits {
  display: block;
  font-size: 11px;
  color: #888888;
  line-height: 1.2;
}
</style>

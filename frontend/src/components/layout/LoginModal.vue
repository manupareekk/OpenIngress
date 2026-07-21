<script setup>
import { ref } from 'vue'
import { useAuth } from '../../composables/useAuth'
import { trackEvent } from '../../lib/analytics'
import LoginProviderIcon from './LoginProviderIcon.vue'

const emit = defineEmits(['close', 'success'])
defineProps({
  title: { type: String, default: 'Log in' },
  subtitle: { type: String, default: 'Sign in to save audits and sync across devices.' }
})

const { loginWithProvider } = useAuth()
const error = ref('')
const loading = ref('')

const signIn = async (provider) => {
  error.value = ''
  loading.value = provider
  try {
    trackEvent('login_started')
    await loginWithProvider(provider)
  } catch (err) {
    error.value = err?.message || 'Sign in failed'
    loading.value = ''
  }
}
</script>

<template>
  <div
    class="fixed inset-0 z-[100] bg-background/80 backdrop-blur-sm flex items-center justify-center p-margin"
    role="dialog"
    aria-modal="true"
    aria-labelledby="login-title"
    @click.self="emit('close')"
  >
    <div class="w-full max-w-md bg-surface-container-lowest border border-outline-variant rounded-xl p-lg">
      <div class="flex justify-between items-start mb-md">
        <h2 id="login-title" class="text-headline-md text-primary font-medium">{{ title }}</h2>
        <button type="button" class="text-secondary hover:text-primary" aria-label="Close" @click="emit('close')">
          <span class="material-symbols-outlined">close</span>
        </button>
      </div>

      <p class="text-body-md text-secondary mb-lg">{{ subtitle }}</p>

      <div class="space-y-sm">
        <button
          type="button"
          class="w-full oi-login-provider-btn"
          :disabled="Boolean(loading)"
          @click="signIn('google')"
        >
          <LoginProviderIcon provider="google" />
          <span>{{ loading === 'google' ? 'Redirecting…' : 'Continue with Google' }}</span>
        </button>
        <button
          type="button"
          class="w-full oi-login-provider-btn"
          :disabled="Boolean(loading)"
          @click="signIn('github')"
        >
          <LoginProviderIcon provider="github" />
          <span>{{ loading === 'github' ? 'Redirecting…' : 'Continue with GitHub' }}</span>
        </button>
      </div>

      <p v-if="error" class="text-[11px] text-red-600 mt-md text-center">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.oi-login-provider-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  padding: 14px 16px;
  border: 1px solid #e5e5e5;
  border-radius: 8px;
  background: #fff;
  color: #111111;
  font: inherit;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.oi-login-provider-btn:hover:not(:disabled) {
  border-color: #111111;
  background: #fafafa;
}

.oi-login-provider-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>

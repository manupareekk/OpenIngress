<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DashIcon from './DashIcon.vue'
import SiteSwitcher from './SiteSwitcher.vue'

const props = defineProps({
  title: { type: String, default: '' },
  sites: { type: Array, default: () => [] }, // [{ key, label }]
  siteKey: { type: String, default: '' }, // '' means all
  navGroups: { type: Array, default: null },
  naturalScroll: { type: Boolean, default: false },
  contextLabel: { type: String, default: '' }
})

const route = useRoute()
const router = useRouter()
const sidebarCollapsed = ref(false)
const mobileNavOpen = ref(false)
const isMobile = ref(false)

const MOBILE_MAX = 767

const syncViewport = () => {
  const mobile = window.matchMedia(`(max-width: ${MOBILE_MAX}px)`).matches
  if (mobile && !isMobile.value) {
    mobileNavOpen.value = false
    sidebarCollapsed.value = true
  }
  if (!mobile && isMobile.value) {
    mobileNavOpen.value = false
    sidebarCollapsed.value = window.localStorage.getItem('oi-dashboard-sidebar') === 'collapsed'
  }
  isMobile.value = mobile
}

const toggleMobileNav = () => {
  mobileNavOpen.value = !mobileNavOpen.value
}

const closeMobileNav = () => {
  mobileNavOpen.value = false
}

const onSidebarNavClick = () => {
  if (isMobile.value) closeMobileNav()
}

const defaultNav = computed(() => [
  {
    label: 'General',
    items: [
      { to: '/app', label: 'Overview', key: 'overview', icon: 'overview' },
      { to: '/app/runs', label: 'Runs', key: 'runs', icon: 'runs' },
      { to: '/app/blockers', label: 'Break points', key: 'blockers', icon: 'analytics' },
      { to: '/app/analytics', label: 'Coverage', key: 'analytics', icon: 'analytics' }
    ]
  }
])

const nav = computed(() =>
  Array.isArray(props.navGroups) && props.navGroups.length ? props.navGroups : defaultNav.value
)
const activeAnchor = ref(route.hash || '')
const contentRef = ref(null)
let scrollRaf = 0
let anchorLockUntil = 0

watch(
  () => route.hash,
  (hash) => {
    activeAnchor.value = hash || activeAnchor.value
  }
)

const hashItems = computed(() =>
  nav.value.flatMap((group) => group.items || []).filter((item) => item.hash)
)

const targetPath = (to) => (typeof to === 'string' ? to : to?.path || '')

const isActive = (to, exact = false) => {
  const path = targetPath(to)
  if (exact) return route.path === path
  if (path === '/app') return route.path === '/app'
  return path ? route.path.startsWith(path) : false
}

const isActiveItem = (item) => {
  if (item.hash) {
    // Prefer the URL hash so sidebar selection matches what the user clicked,
    // even when the target is already on-screen and scroll-spy would pick another section.
    if (route.hash) return route.hash === item.hash
    return activeAnchor.value === item.hash
  }
  return isActive(item.to, Boolean(item.exact))
}

const syncActiveAnchorFromScroll = () => {
  if (Date.now() < anchorLockUntil) return
  const container = contentRef.value
  if (!container || !hashItems.value.length) return
  const containerTop = container.getBoundingClientRect().top
  const sections = hashItems.value
    .map((item) => {
      const el = document.getElementById(String(item.hash).replace(/^#/, ''))
      if (!el) return null
      return {
        hash: item.hash,
        top: el.getBoundingClientRect().top - containerTop
      }
    })
    .filter(Boolean)
  if (!sections.length) return

  const threshold = 96
  const active =
    [...sections].reverse().find((section) => section.top <= threshold) ||
    sections.find((section) => section.top > threshold)
  if (!active?.hash) return
  activeAnchor.value = active.hash
  // If the user scrolled away from the URL hash section, drop the hash so the
  // highlight tracks what's on screen instead of staying stuck on Break points.
  if (route.hash && route.hash !== active.hash) {
    router.replace({ path: route.path, query: route.query, hash: '' }).catch(() => {})
  }
}

const requestScrollSync = () => {
  if (scrollRaf) return
  scrollRaf = window.requestAnimationFrame(() => {
    scrollRaf = 0
    syncActiveAnchorFromScroll()
  })
}

const resetContentScroll = () => {
  if (!route.hash && contentRef.value) contentRef.value.scrollTop = 0
}

const goToAnchor = async (hash) => {
  const container = contentRef.value
  const id = String(hash || '').replace(/^#/, '')
  activeAnchor.value = hash || ''
  anchorLockUntil = Date.now() + 1200
  try {
    await router.replace({ path: route.path, query: route.query, hash })
  } catch {
    // Same-hash clicks can be ignored; scroll/highlight below still runs.
  }
  await nextTick()
  const target = document.getElementById(id)
  if (target) {
    const details = target.closest('details')
    if (details && !details.open) details.open = true
    target.classList.remove('oi-anchor-flash')
    // Force reflow so the animation can retrigger on repeated clicks.
    void target.offsetWidth
    target.classList.add('oi-anchor-flash')
    if (container) {
      const top =
        container.scrollTop +
        target.getBoundingClientRect().top -
        container.getBoundingClientRect().top -
        18
      container.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
    }
  }
  window.setTimeout(() => {
    anchorLockUntil = 0
  }, 1200)
}

onMounted(() => {
  syncViewport()
  window.addEventListener('resize', syncViewport)
  if (!isMobile.value) {
    sidebarCollapsed.value = window.localStorage.getItem('oi-dashboard-sidebar') === 'collapsed'
  }
  nextTick(syncActiveAnchorFromScroll)
  contentRef.value?.addEventListener('scroll', requestScrollSync, { passive: true })
  window.addEventListener('resize', requestScrollSync)
  if (route.hash) {
    nextTick(() => goToAnchor(route.hash))
    window.setTimeout(() => goToAnchor(route.hash), 120)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncViewport)
  contentRef.value?.removeEventListener('scroll', requestScrollSync)
  window.removeEventListener('resize', requestScrollSync)
  if (scrollRaf) window.cancelAnimationFrame(scrollRaf)
})

watch(hashItems, () => nextTick(syncActiveAnchorFromScroll))
watch(
  () => route.fullPath,
  (path, prevPath) => {
    closeMobileNav()
    // Only reset to top on real page changes, never on hash-only navigations.
    const pathOnly = String(path || '').split('#')[0]
    const prevOnly = String(prevPath || '').split('#')[0]
    if (pathOnly === prevOnly) return
    if (route.hash) {
      nextTick(() => goToAnchor(route.hash))
      window.setTimeout(() => goToAnchor(route.hash), 120)
      return
    }
    nextTick(resetContentScroll)
  }
)

const toWithQuery = (target) => {
  if (typeof target === 'string') return { path: target, query: route.query }
  if (target?.preserveQuery === false) {
    const { preserveQuery, ...cleanTarget } = target
    return cleanTarget
  }
  return {
    ...target,
    query: {
      ...route.query,
      ...(target.query || {})
    }
  }
}
watch(sidebarCollapsed, (collapsed) => {
  if (!isMobile.value) {
    window.localStorage.setItem('oi-dashboard-sidebar', collapsed ? 'collapsed' : 'expanded')
  }
})
</script>

<template>
  <div
    class="oi-dash-shell"
    :class="{
      'is-collapsed': sidebarCollapsed && !isMobile,
      'is-mobile-nav-open': mobileNavOpen,
      'is-mobile': isMobile,
      'is-natural-scroll': props.naturalScroll
    }"
  >
    <button
      v-if="isMobile && mobileNavOpen"
      type="button"
      class="oi-dash-mobile-backdrop"
      aria-label="Close navigation"
      @click="closeMobileNav"
    />

    <div class="oi-dash-layout">
      <aside id="dashboard-sidebar" class="oi-dash-sidebar">
        <button
          v-if="!isMobile"
          type="button"
          class="oi-dash-collapse-handle"
          :aria-label="sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          :aria-expanded="sidebarCollapsed ? 'false' : 'true'"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <span aria-hidden="true">{{ sidebarCollapsed ? '›' : '‹' }}</span>
        </button>

        <div
          class="oi-dash-sidebar-head"
          :class="{ 'is-single-column': contextLabel }"
        >
          <div class="oi-dash-sidebar-brand min-w-0 oi-dash-collapse-hide">
            <div class="text-body-md font-medium truncate">OpenIngress</div>
            <div class="mt-xs text-body-md oi-dash-muted truncate">Local workspace</div>
            <div v-if="contextLabel" class="oi-dash-site-context">{{ contextLabel }}</div>
          </div>
          <router-link
            to="/app/new"
            class="oi-dash-btn oi-dash-btn-primary oi-dash-new-btn"
            title="New study"
          >
            <span class="oi-dash-new-expanded-icon oi-dash-icon" aria-hidden="true">
              <DashIcon name="plus" />
            </span>
            <span class="oi-dash-expanded-label">New</span>
            <span class="oi-dash-icon oi-dash-collapsed-label" aria-hidden="true">
              <DashIcon name="plus" />
            </span>
          </router-link>
        </div>

        <SiteSwitcher v-if="!contextLabel" :sites="props.sites" :selected="props.siteKey" />

        <nav aria-label="Dashboard navigation">
          <div v-for="group in nav" :key="group.label" class="oi-dash-navgroup">
            <div v-if="group.label" class="oi-dash-navlabel">{{ group.label }}</div>
            <template v-for="item in group.items" :key="item.key">
              <a
                v-if="item.hash"
                :href="item.hash"
                class="oi-dash-navitem"
                :class="{ 'is-active': isActiveItem(item) }"
                @click.prevent="goToAnchor(item.hash); onSidebarNavClick()"
              >
                <span class="oi-dash-icon" aria-hidden="true">
                  <DashIcon :name="item.icon" />
                </span>
                <span class="truncate oi-dash-collapse-hide">{{ item.label }}</span>
              </a>
              <router-link
                v-else
                :to="toWithQuery(item.to)"
                class="oi-dash-navitem"
                :class="{ 'is-active': isActiveItem(item) }"
                @click="onSidebarNavClick"
              >
                <span class="oi-dash-icon" aria-hidden="true">
                  <DashIcon :name="item.icon" />
                </span>
                <span class="truncate oi-dash-collapse-hide">{{ item.label }}</span>
              </router-link>
            </template>
          </div>
        </nav>

        <div class="mt-auto pt-lg oi-dash-collapse-hide">
          <div class="oi-dash-navitem" style="cursor: default;">
            <span class="oi-dash-icon" aria-hidden="true">
              <DashIcon name="overview" />
            </span>
            <span class="min-w-0">
              <span class="block truncate" style="font-size: 13px; font-weight: 500;">OpenIngress</span>
              <span class="block truncate oi-dash-muted" style="font-size: 12px;">Self-hosted engine</span>
            </span>
          </div>
        </div>
      </aside>

      <section class="oi-dash-main">
        <header class="oi-dash-topbar">
          <div class="flex min-w-0 items-center gap-sm">
            <button
              v-if="isMobile"
              type="button"
              class="oi-dash-btn oi-dash-btn-ghost oi-dash-mobile-menu-btn"
              :aria-expanded="mobileNavOpen ? 'true' : 'false'"
              aria-controls="dashboard-sidebar"
              @click="toggleMobileNav"
            >
              Menu
            </button>
            <div class="min-w-0">
              <div class="oi-dash-section-title truncate">
                {{ props.title }}
              </div>
            </div>
          </div>
          <div class="flex items-center justify-end gap-sm min-w-0">
            <slot name="topbar" />
          </div>
        </header>

        <main ref="contentRef" class="oi-dash-content">
          <slot />
        </main>
      </section>
    </div>
  </div>
</template>

import { onMounted, onUnmounted, ref } from 'vue'

/** Fade/slide chart content in when scrolled into view (once). */
export function useChartReveal(options = {}) {
  const root = ref(null)
  const visible = ref(false)
  let observer

  onMounted(() => {
    if (typeof IntersectionObserver === 'undefined') {
      visible.value = true
      return
    }
    observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          visible.value = true
          observer?.disconnect()
        }
      },
      { threshold: options.threshold ?? 0.12, rootMargin: options.rootMargin ?? '0px 0px -40px 0px' }
    )
    if (root.value) observer.observe(root.value)
  })

  onUnmounted(() => {
    observer?.disconnect()
  })

  return { root, visible }
}

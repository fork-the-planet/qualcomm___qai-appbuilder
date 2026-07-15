<script setup lang="ts">
/**
 * Theme toggle button.
 *
 * S5 PR-052: cycles through light → dark → auto and updates
 * `useUiStore`. The actual `data-theme` attribute is applied by
 * `useTheme()` watching the store.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useTheme } from "@/composables/useTheme";

const { theme, cycleTheme } = useTheme();
const { t } = useI18n();

const labelKey = computed(() => {
  switch (theme.value) {
    case "light":
      return "theme.light";
    case "dark":
      return "theme.dark";
    case "auto":
    default:
      return "theme.auto";
  }
});

const icon = computed(() => {
  switch (theme.value) {
    case "light":
      return "☀";
    case "dark":
      return "☾";
    case "auto":
    default:
      return "◐";
  }
});
</script>

<template>
  <button
    type="button"
    class="theme-toggle"
    :aria-label="t('theme.toggle')"
    :title="t(labelKey)"
    @click="cycleTheme"
  >
    <span
      class="theme-toggle__icon"
      aria-hidden="true"
    >{{ icon }}</span>
    <span class="theme-toggle__label">{{ t(labelKey) }}</span>
  </button>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border);
  background: var(--bg-primary);
  color: var(--text-primary);
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
}

.theme-toggle:hover {
  border-color: var(--accent);
}

.theme-toggle__icon {
  display: inline-block;
  width: 1em;
  text-align: center;
}
</style>

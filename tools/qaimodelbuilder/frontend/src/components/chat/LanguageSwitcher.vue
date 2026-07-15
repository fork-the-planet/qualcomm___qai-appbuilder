<script setup lang="ts">
/**
 * LanguageSwitcher — locale dropdown switcher.
 *
 * Changes the active i18n locale. Persists selection to localStorage.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useUiStore } from "@/stores/ui";

interface Props {
  compact?: boolean;
}

withDefaults(defineProps<Props>(), {
  compact: false,
});

const { locale, availableLocales } = useI18n();
const ui = useUiStore();

const LOCALE_LABELS: Record<string, string> = {
  en: "English",
  zh: "Chinese",
  "zh-CN": "Chinese (Simplified)",
  "zh-TW": "Chinese (Traditional)",
  ja: "Japanese",
  ko: "Korean",
};

const options = computed(() =>
  availableLocales.map((code) => ({
    code,
    label: LOCALE_LABELS[code] ?? code,
  })),
);

function setLocale(code: string): void {
  // Route through the ui store so the choice is persisted to localStorage
  // (single source of truth); App.vue's watcher mirrors ui.locale → i18n.
  ui.setLocale(code);
  // Apply immediately too so the dropdown reflects the change without
  // waiting for the watcher tick.
  locale.value = code;
}
</script>

<template>
  <div class="language-switcher">
    <label
      v-if="!compact"
      class="language-switcher__label"
    >
      Language
    </label>
    <select
      class="language-switcher__select"
      :value="locale"
      @change="setLocale(($event.target as HTMLSelectElement).value)"
    >
      <option
        v-for="opt in options"
        :key="opt.code"
        :value="opt.code"
      >
        {{ opt.label }}
      </option>
    </select>
  </div>
</template>

<style scoped>
.language-switcher {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.language-switcher__label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-muted);
}

.language-switcher__select {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
}
</style>

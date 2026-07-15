<script setup lang="ts">
/**
 * Locale switcher.
 *
 * S5 PR-052: replaces the inline buttons that lived in `App.vue` for
 * PR-050. Uses a native `<select>` for accessibility (screen readers
 * announce options without bespoke ARIA).
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useUiStore, type AppLocale } from "@/stores/ui";
import { SUPPORTED_LOCALES, type SupportedLocale } from "@/locales";

const { t, locale } = useI18n();
const ui = useUiStore();

const value = computed<SupportedLocale>({
  get: () => ui.locale,
  set: (next) => {
    ui.setLocale(next);
    locale.value = next;
  },
});

const options: ReadonlyArray<{ value: AppLocale; label: string }> = [
  { value: "en", label: "English" },
  { value: "zh-CN", label: "简体中文" },
  { value: "zh-TW", label: "繁體中文" },
];

// Compile-time guard: fail early if SUPPORTED_LOCALES drifts from this list.
{
  const supported = new Set<string>(SUPPORTED_LOCALES);
  for (const o of options) {
    if (!supported.has(o.value)) {
      throw new Error(`LocaleSwitcher option ${o.value} not in SUPPORTED_LOCALES`);
    }
  }
}
</script>

<template>
  <label class="locale-switcher">
    <span class="locale-switcher__sr">{{ t("language.srLabel") }}</span>
    <select
      v-model="value"
      class="locale-switcher__select"
    >
      <option
        v-for="opt in options"
        :key="opt.value"
        :value="opt.value"
      >
        {{ opt.label }}
      </option>
    </select>
  </label>
</template>

<style scoped>
.locale-switcher {
  display: inline-flex;
  align-items: center;
}

.locale-switcher__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.locale-switcher__select {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border);
  background: var(--bg-primary);
  color: var(--text-primary);
  border-radius: 6px;
  font: inherit;
}
</style>

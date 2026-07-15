<!--
  DialogHeader — shared modal header (optional back button + title + close).

  Extracted so modal dialogs (e.g. TemplateLibraryDialog) stop each hand-rolling
  their own header markup (§3.6 cohesion). When a dialog is opened FROM another
  panel, pass `show-back` so the user can return to the previous panel instead
  of only being able to close out entirely.

  §3.9.2: presentational only; no native dialogs. Emits `back` / `close`.
-->
<script setup lang="ts">
import { useI18n } from "vue-i18n";

defineProps<{
  /** Header title text. */
  title: string;
  /** Show the back arrow (return to the panel that opened this one). */
  showBack?: boolean;
}>();

const emit = defineEmits<{
  (e: "back"): void;
  (e: "close"): void;
}>();

const { t } = useI18n();
</script>

<template>
  <header class="dialog-header">
    <button
      v-if="showBack"
      type="button"
      class="dialog-header__back"
      data-testid="dialog-back"
      :title="t('common.back')"
      :aria-label="t('common.back')"
      @click="emit('back')"
    >
      ←
    </button>
    <h2 class="dialog-header__title">{{ title }}</h2>
    <button
      type="button"
      class="dialog-header__close"
      data-testid="dialog-close"
      :title="t('common.cancel')"
      :aria-label="t('common.cancel')"
      @click="emit('close')"
    >
      ✕
    </button>
  </header>
</template>

<style scoped>
.dialog-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dialog-header__title {
  flex: 1;
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #e6e6e6);
}
.dialog-header__back,
.dialog-header__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary, #a0a0a0);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}
.dialog-header__back:hover,
.dialog-header__close:hover {
  background: var(--surface-hover, rgba(255, 255, 255, 0.08));
  color: var(--text-primary, #e6e6e6);
}
</style>

<script setup lang="ts">
/**
 * ToolbarMode — thin presentational streaming-mode indicator.
 *
 * Shown inside ChatComposer when the active tab is streaming.
 * Displays a mode label and provides a stop button that emits `stop`.
 * Tool-mode navigation is handled by the ToolsLandingView routing
 * system; this component only reflects the current streaming state.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useUiStore } from "@/stores/ui";

interface Props {
  /** Whether the chat input is blocked (e.g. during reboot). */
  isBlocked?: boolean;
  /** Whether this tab is the one actively streaming. */
  isStreamingHere?: boolean;
  /** Optional override for the mode label text. */
  modeLabel?: string;
}

const props = withDefaults(defineProps<Props>(), {
  isBlocked: false,
  isStreamingHere: false,
  modeLabel: "",
});

const emit = defineEmits<{
  exit: [];
  send: [];
  stop: [];
}>();

const { t } = useI18n();
const uiStore = useUiStore();

/** Resolved label: explicit prop > active tool mode > fallback. */
const label = computed(() => {
  if (props.modeLabel) return props.modeLabel;
  if (uiStore.activeToolMode) return uiStore.activeToolMode;
  return t("chat.stopGenerating");
});

function onStop(): void {
  emit("stop");
}
</script>

<template>
  <div
    class="qai-toolbar-mode"
    :class="{ 'qai-toolbar-mode--streaming': isStreamingHere }"
  >
    <span class="qai-toolbar-mode__label">{{ label }}</span>
    <button
      v-if="isStreamingHere"
      type="button"
      class="qai-toolbar-mode__stop"
      :disabled="isBlocked"
      @click="onStop"
    >
      {{ t("chat.stopGenerating") }}
    </button>
    <slot />
  </div>
</template>

<style scoped>
.qai-toolbar-mode {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-radius: 6px;
  background: var(--bg-secondary, var(--bg-primary));
}

.qai-toolbar-mode--streaming {
  border: 1px solid var(--border);
}

.qai-toolbar-mode__label {
  font-size: var(--text-sm);
  color: var(--text-muted);
  white-space: nowrap;
}

.qai-toolbar-mode__stop {
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-sm);
  border: none;
  border-radius: 4px;
  background: var(--error, #e53e3e);
  color: #fff;
  cursor: pointer;
}

.qai-toolbar-mode__stop:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

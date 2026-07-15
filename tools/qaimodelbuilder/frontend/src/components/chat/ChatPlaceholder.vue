<script setup lang="ts">
/**
 * ChatPlaceholder — empty chat state welcome-screen.
 *
 * V2 brand mark: neural-network nodes + NPU chip motif with
 * brand gradient (#7c6cff → #60a5fa). CSS in chat.css drives
 * sizing, colors, and animations (welcome-float / frame-flow).
 *
 * Rendering decision:
 *   The component keeps the `.chat-placeholder` root class so existing
 *   smoke tests (`pr053-sfc-smoke.spec.ts`) still find it, but the inner
 *   markup uses `.welcome-icon` / `.welcome-title` / `.welcome-subtitle`
 *   / `.welcome-chips` / `.welcome-chip` class names so global `chat.css`
 *   styles apply.
 *
 * The default suggestions (welcome chips) match i18n keys
 *   `chat.welcomeChip{1,2,3}{Label,Prompt}`. Callers may still override
 *   the title / body via `titleKey` / `bodyKey` props.
 *
 * ChatMessageList renders its own welcome screen inline and is the
 * canonical empty-state surface inside the chat view; this component is
 * available for any other view that wants the same look-and-feel.
 */
import { useI18n } from "vue-i18n";

interface Props {
  titleKey?: string;
  bodyKey?: string;
}

const props = withDefaults(defineProps<Props>(), {
  titleKey: "chat.welcomeTitle",
  bodyKey: "chat.welcomeSubtitle",
});

const emit = defineEmits<{
  "select-suggestion": [text: string];
}>();

const { t } = useI18n();

// V1 welcome chips (frontend/index.html:435-443 + i18n keys
// chat.welcomeChip{1,2,3}{Label,Prompt}).
const chips = [
  { id: "chip1", labelKey: "chat.welcomeChip1Label", promptKey: "chat.welcomeChip1Prompt" },
  { id: "chip2", labelKey: "chat.welcomeChip2Label", promptKey: "chat.welcomeChip2Prompt" },
  { id: "chip3", labelKey: "chat.welcomeChip3Label", promptKey: "chat.welcomeChip3Prompt" },
  { id: "chip4", labelKey: "chat.welcomeChip4Label", promptKey: "chat.welcomeChip4Prompt" },
  { id: "chip5", labelKey: "chat.welcomeChip5Label", promptKey: "chat.welcomeChip5Prompt" },
  { id: "chip6", labelKey: "chat.welcomeChip6Label", promptKey: "chat.welcomeChip6Prompt" },
] as const;

function selectChip(promptKey: string): void {
  emit("select-suggestion", t(promptKey));
}
</script>

<template>
  <!-- Root keeps `.chat-placeholder` for backwards compat with existing
       smoke tests; `.welcome-screen` is the V1-parity class that the
       global chat.css drives. -->
  <div
    class="chat-placeholder welcome-screen"
    role="status"
    aria-live="polite"
  >
    <!-- V2 brand mark — AI neural-network + NPU chip motif.
         CSS in chat.css drives sizing, colors, and the
         welcome-float / welcome-frame-flow animations. -->
    <div
      class="welcome-icon"
      aria-hidden="true"
    >
      <svg
        class="welcome-logo-glyph"
        viewBox="0 0 112 112"
        fill="none"
      >
        <defs>
          <linearGradient id="wl-brand-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#7c6cff"/>
            <stop offset="100%" stop-color="#60a5fa"/>
          </linearGradient>
        </defs>
        <rect
          class="welcome-logo-tile"
          x="4" y="4" width="104" height="104" rx="24"
        />
        <g class="welcome-logo-frame">
          <line x1="56" y1="22" x2="34" y2="38"/>
          <line x1="56" y1="22" x2="78" y2="38"/>
          <line x1="34" y1="38" x2="22" y2="56"/>
          <line x1="78" y1="38" x2="90" y2="56"/>
          <line x1="22" y1="56" x2="34" y2="74"/>
          <line x1="90" y1="56" x2="78" y2="74"/>
          <line x1="34" y1="74" x2="56" y2="90"/>
          <line x1="78" y1="74" x2="56" y2="90"/>
          <line x1="34" y1="38" x2="56" y2="56"/>
          <line x1="78" y1="38" x2="56" y2="56"/>
          <line x1="22" y1="56" x2="56" y2="56"/>
          <line x1="90" y1="56" x2="56" y2="56"/>
          <line x1="34" y1="74" x2="56" y2="56"/>
          <line x1="78" y1="74" x2="56" y2="56"/>
        </g>
        <g class="welcome-logo-pulse">
          <rect x="44" y="44" width="24" height="24" rx="4" stroke-linecap="round"/>
          <line x1="50" y1="44" x2="50" y2="39"/>
          <line x1="56" y1="44" x2="56" y2="39"/>
          <line x1="62" y1="44" x2="62" y2="39"/>
          <line x1="50" y1="68" x2="50" y2="73"/>
          <line x1="56" y1="68" x2="56" y2="73"/>
          <line x1="62" y1="68" x2="62" y2="73"/>
          <line x1="44" y1="50" x2="39" y2="50"/>
          <line x1="44" y1="56" x2="39" y2="56"/>
          <line x1="44" y1="62" x2="39" y2="62"/>
          <line x1="68" y1="50" x2="73" y2="50"/>
          <line x1="68" y1="56" x2="73" y2="56"/>
          <line x1="68" y1="62" x2="73" y2="62"/>
          <line x1="49" y1="52" x2="56" y2="52"/>
          <line x1="56" y1="52" x2="56" y2="60"/>
          <line x1="56" y1="60" x2="63" y2="60"/>
        </g>
        <g class="welcome-logo-nodes">
          <circle cx="56" cy="22" r="4.5"/>
          <circle cx="34" cy="38" r="3.5"/>
          <circle cx="78" cy="38" r="3.5"/>
          <circle cx="22" cy="56" r="3"/>
          <circle cx="90" cy="56" r="3"/>
          <circle cx="34" cy="74" r="3.5"/>
          <circle cx="78" cy="74" r="3.5"/>
          <circle cx="56" cy="90" r="4.5"/>
        </g>
      </svg>
    </div>
    <div class="welcome-title">
      {{ t(props.titleKey) }}
    </div>
    <div class="welcome-subtitle">
      {{ t(props.bodyKey) }}
    </div>
    <div class="welcome-chips">
      <button
        v-for="chip in chips"
        :key="chip.id"
        type="button"
        class="welcome-chip"
        :title="t(chip.promptKey)"
        @click="selectChip(chip.promptKey)"
      >
        {{ t(chip.labelKey) }}
      </button>
    </div>
  </div>
</template>

<style scoped>
/* Visual styling lives in the global chat.css (.welcome-screen
   / .welcome-icon / .welcome-title / .welcome-subtitle / .welcome-chips
   / .welcome-chip). This component keeps no scoped overrides so the
   placeholder matches V1 (and ChatMessageList's inline welcome screen)
   exactly. */
</style>

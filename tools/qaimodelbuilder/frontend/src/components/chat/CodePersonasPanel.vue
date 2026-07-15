<script setup lang="ts">
/**
 * CodePersonasPanel — coding-persona system-prompt editor.
 *
 * V1 parity (`CodePersonasPanel.js`): a row-based accordion where each
 * built-in persona is one collapsible row. Expanding a row reveals an
 * inline system-prompt editor with draft/dirty tracking, Save / Cancel /
 * Reset-to-default, an "is_customized" badge, and a Reload action. Only
 * one row is open at a time (accordion); switching away from a row with
 * unsaved edits asks for discard confirmation.
 *
 * V1 is the behaviour source of truth, but the implementation is rebuilt
 * for V2: the panel reuses the global `.cp-*` accordion styles from
 * `settings.css` (no bespoke card grid / undefined classes) and the
 * shared `useConfirm()` custom dialog instead of `window.confirm`.
 *
 * Endpoints (via `useCodePersonas`):
 *   GET    /api/code-personas          → { selected, personas: [...] }
 *   POST   /api/code-personas/:id       { prompt }   (save override)
 *   DELETE /api/code-personas/:id       (reset to built-in default)
 */
import { ref, computed, onMounted } from "vue";
import { useI18n } from "vue-i18n";
import { useCodePersonas, type Persona } from "@/composables/useCodePersonas";
import { useConfirm } from "@/composables/useConfirm";

// ─── State ───────────────────────────────────────────────────────────────────

const { t } = useI18n();
const { confirm } = useConfirm();

/**
 * Localized persona name/description (V1 `useCodePersonas.js:localizedName`
 * / `localizedDescription`): prefer the built-in i18n key
 * (`codePersona.{id}.name` / `.desc`) so the English UI shows English names
 * even when the backend returns the Chinese defaults; fall back to the
 * backend-provided `persona.name` / `description` for any custom persona
 * without an i18n entry.
 */
function localizedName(persona: Persona): string {
  const key = `codePersona.${persona.id}.name`;
  const tr = t(key);
  if (tr && tr !== key) return tr;
  return persona.name || persona.id;
}
function localizedDescription(persona: Persona): string {
  const key = `codePersona.${persona.id}.desc`;
  const tr = t(key);
  if (tr && tr !== key) return tr;
  return persona.description ?? "";
}

const {
  personas,
  loading,
  saving,
  fetchPersonas,
  savePersonaPrompt,
  resetPersonaPrompt,
} = useCodePersonas({ t, localizedName });

const search = ref("");

// Accordion: which persona id is expanded (only one) + its draft text.
const expandedId = ref<string | null>(null);
const draftPrompt = ref("");

// Tracks whether the initial fetch has completed (V1 `loaded`).
const loaded = ref(false);

// ─── Computed ────────────────────────────────────────────────────────────────

const filteredPersonas = computed(() => {
  const q = search.value.toLowerCase().trim();
  if (!q) return personas.value;
  return personas.value.filter(
    (p) =>
      localizedName(p).toLowerCase().includes(q) ||
      localizedDescription(p).toLowerCase().includes(q),
  );
});

/** Effective prompt for a persona (override falls back to default). */
function effectivePrompt(id: string): string {
  const p = personas.value.find((x) => x.id === id);
  if (!p) return "";
  return p.prompt && p.prompt.length > 0 ? p.prompt : (p.default_prompt ?? "");
}

/** Dirty when the draft differs from the expanded persona's effective prompt. */
const isDirty = computed(() => {
  if (expandedId.value === null) return false;
  return effectivePrompt(expandedId.value) !== draftPrompt.value;
});

// ─── Actions ─────────────────────────────────────────────────────────────────

async function confirmDiscard(): Promise<boolean> {
  return confirm({
    title: t("codePersona.unsavedChanges"),
    message: t("codePersona.discardConfirm"),
    confirmStyle: "danger",
  });
}

async function toggleExpanded(id: string): Promise<void> {
  if (expandedId.value === id) {
    // Collapsing the open row — warn on unsaved changes.
    if (isDirty.value && !(await confirmDiscard())) return;
    expandedId.value = null;
    return;
  }
  // Opening a new row — warn if the currently open row has unsaved edits.
  if (expandedId.value !== null && isDirty.value && !(await confirmDiscard())) {
    return;
  }
  draftPrompt.value = effectivePrompt(id);
  expandedId.value = id;
}

async function handleSavePrompt(id: string): Promise<void> {
  if (!isDirty.value) return;
  const ok = await savePersonaPrompt(id, draftPrompt.value);
  if (ok) draftPrompt.value = effectivePrompt(id);
}

async function cancelEdit(): Promise<void> {
  if (isDirty.value && !(await confirmDiscard())) return;
  expandedId.value = null;
}

async function handleResetPrompt(id: string): Promise<void> {
  const persona = personas.value.find((p) => p.id === id);
  // Only customized personas can be reset (V1 gating).
  if (!persona || persona.is_customized === false) return;
  const ok = await confirm({
    title: t("codePersona.resetToDefault"),
    message: t("codePersona.resetConfirm", { name: localizedName(persona) }),
    confirmStyle: "danger",
  });
  if (!ok) return;
  const reset = await resetPersonaPrompt(id);
  if (reset && expandedId.value === id) {
    draftPrompt.value = effectivePrompt(id);
  }
}

async function handleReload(): Promise<void> {
  if (expandedId.value !== null && isDirty.value && !(await confirmDiscard())) {
    return;
  }
  expandedId.value = null;
  await fetchPersonas();
}

onMounted(async () => {
  await fetchPersonas();
  loaded.value = true;
});
</script>

<template>
  <div class="cp-page">
    <!-- Intro + reload (V1 cp-page-intro) -->
    <div class="cp-page-intro">
      <div class="cp-page-intro-text">
        {{ t("codePersona.settingsDesc") }}
      </div>
      <div class="cp-page-intro-actions">
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          :disabled="loading"
          :title="t('codePersona.reloadHint')"
          data-testid="persona-reload"
          @click="handleReload"
        >
          <span
            v-if="loading"
            class="spinner"
            style="width: 11px; height: 11px; border-width: 2px; margin-right: 4px"
          ></span>
          <span
            v-else
            style="margin-right: 2px"
          >&#x21BB;</span>
          {{ t("codePersona.reload") }}
        </button>
      </div>
    </div>

    <!-- Search (V2 enhancement) -->
    <div class="config-field">
      <input
        v-model="search"
        type="text"
        class="config-input"
        :placeholder="t('common.search') + '...'"
      />
    </div>

    <!-- Loading placeholder (V1 cp-page-loading) -->
    <div
      v-if="loading && !loaded"
      class="cp-page-loading"
    >
      <span
        class="spinner"
        style="width: 14px; height: 14px; border-width: 2px; margin-right: 8px"
      ></span>
      {{ t("codePersona.loading") }}
    </div>

    <!-- Persona accordion list (V1 cp-page-list) -->
    <div class="cp-page-list">
      <div
        v-for="persona in filteredPersonas"
        :key="persona.id"
        class="cp-row"
      >
        <div
          class="cp-row-header"
          role="button"
          :tabindex="0"
          @click="toggleExpanded(persona.id)"
          @keydown.enter="toggleExpanded(persona.id)"
          @keydown.space.prevent="toggleExpanded(persona.id)"
        >
          <div class="cp-row-title">
            <span class="cp-row-name">{{ localizedName(persona) }}</span>
            <span
              v-if="persona.is_customized"
              class="cp-row-customized"
              :title="t('codePersona.customizedHint')"
              :data-testid="`persona-customized-${persona.id}`"
            >
              {{ t("codePersona.customizedTag") }}
            </span>
          </div>
          <div class="cp-row-desc">
            {{ localizedDescription(persona) }}
          </div>
          <span
            class="collapse-arrow"
            :class="{ collapsed: expandedId !== persona.id }"
          >&#9660;</span>
        </div>

        <div
          v-if="expandedId === persona.id"
          class="cp-row-body"
        >
          <label class="config-label cp-prompt-label">
            {{ t("codePersona.promptLabel") }}
          </label>
          <textarea
            v-model="draftPrompt"
            class="config-input cp-prompt-textarea"
            spellcheck="false"
            wrap="soft"
            :placeholder="t('codePersona.promptPlaceholder')"
            :data-testid="`persona-prompt-${persona.id}`"
          ></textarea>
          <div class="cp-row-footer">
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="!isDirty || saving"
              :data-testid="`persona-save-${persona.id}`"
              @click="handleSavePrompt(persona.id)"
            >
              <span
                v-if="saving"
                class="spinner"
                style="width: 11px; height: 11px; border-width: 2px; margin-right: 4px"
              ></span>
              &#x1F4BE; {{ t("codePersona.save") }}
            </button>
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              :disabled="!isDirty"
              :data-testid="`persona-cancel-${persona.id}`"
              @click="cancelEdit()"
            >
              {{ t("codePersona.cancel") }}
            </button>
            <button
              type="button"
              class="btn btn-ghost btn-sm cp-row-reset"
              :disabled="saving || persona.is_customized === false"
              :title="persona.is_customized === false ? t('codePersona.alreadyDefaultHint') : ''"
              :data-testid="`persona-reset-${persona.id}`"
              @click="handleResetPrompt(persona.id)"
            >
              &#x21BA; {{ t("codePersona.resetToDefault") }}
            </button>
          </div>
          <div
            v-if="isDirty"
            class="cp-row-dirty-hint"
          >
            {{ t("codePersona.unsavedChanges") }}
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="filteredPersonas.length === 0 && loaded"
      class="cp-page-loading"
    >
      {{ t("codePersona.noModesFound") }}
    </div>
  </div>
</template>

<style scoped>
/* Accordion arrow rotation/colour for cp-row headers (settings.css only
   sets layout for `.cp-row-header .collapse-arrow`). */
.cp-row-header .collapse-arrow {
  font-size: var(--text-xs);
  color: var(--text-muted);
  transition: transform 0.2s;
}
.cp-row-header .collapse-arrow.collapsed {
  transform: rotate(-90deg);
}
.cp-prompt-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
/* Push reset to the far right within the footer (V1 margin-left:auto). */
.cp-row-reset {
  margin-left: auto;
}
</style>

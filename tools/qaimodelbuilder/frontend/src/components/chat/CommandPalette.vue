<script setup lang="ts">
/**
 * CommandPalette — VS Code-style global command launcher overlay.
 *
 * V1 parity (frontend/js/components/CommandPalette.js + css/utilities.css
 * `.cmd-palette*`, lines 242-358): the palette groups its results into
 * sections (Actions / Skills / Models …) each with a group icon + label,
 * and every item renders an icon, a label and an optional keyboard
 * shortcut. Keyboard navigation (↑/↓/Enter/Esc) walks across the flattened
 * group → item order exactly like V1's moveDown/moveUp.
 *
 * Behaviour source of truth = V1; the implementation here is a typed Vue 3
 * SFC that derives the groups from the shared `useCommandPalette`
 * composable's flat command list (grouped by `category`), instead of V1's
 * hand-rolled `groupedResults` over global refs. Group labels/icons are
 * localized via the existing `commandPalette.group.*` i18n keys.
 *
 * Visuals are owned by the global `.cmd-palette*` rules migrated to
 * `styles/common/utilities.css`, so no scoped CSS / BEM rewrite — the card
 * stays 1:1 with V1.
 */
import { ref, computed, watch, nextTick } from "vue";
import { useI18n } from "vue-i18n";
import { useCommandPaletteStore } from "@/stores/commandPalette";
import { useCommandPalette, type PaletteCommand } from "@/composables/useCommandPalette";

interface Props {
  visible?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  visible: undefined,
});

const emit = defineEmits<{
  "update:visible": [value: boolean];
}>();

const { t } = useI18n();
const store = useCommandPaletteStore();
const { filtered, hide, setQuery } = useCommandPalette({ bindShortcut: false });

const inputRef = ref<HTMLInputElement | null>(null);
/** Active position as a flat index across all group items (V1 activeGroupIdx
 *  + activeItemIdx collapse to a single running index here). */
const activeIndex = ref(0);

const isOpen = computed(() => props.visible ?? store.open);

// ── Grouping (V1 groupedResults, CommandPalette.js:142-154) ──────────────────
// V1 ordered the groups Actions → Skills → Models. We honour that ordering for
// the known categories and append any other categories afterwards in
// first-seen order. Each group carries its localized label + leading icon.
interface PaletteGroup {
  key: string;
  label: string;
  icon: string;
  items: readonly PaletteCommand[];
}

/** Category → { label, icon } (V1 group.* labels + group icons). Unknown
 *  categories fall back to a generic gear icon and their raw category name. */
const GROUP_META: Record<string, { labelKey: string; icon: string }> = {
  actions: { labelKey: "commandPalette.group.actions", icon: "\u2699" },
  skills: { labelKey: "commandPalette.group.skills", icon: "\u26A1" },
  models: { labelKey: "commandPalette.group.models", icon: "\u{1F916}" },
};
const GROUP_ORDER = ["actions", "skills", "models"];

const groups = computed<PaletteGroup[]>(() => {
  const byCategory = new Map<string, PaletteCommand[]>();
  for (const cmd of filtered.value) {
    const key = (cmd.category ?? "").trim() === "" ? "actions" : (cmd.category as string);
    const existing = byCategory.get(key);
    if (existing === undefined) byCategory.set(key, [cmd]);
    else existing.push(cmd);
  }

  const ordered: string[] = [];
  for (const k of GROUP_ORDER) {
    if (byCategory.has(k)) ordered.push(k);
  }
  for (const k of byCategory.keys()) {
    if (!ordered.includes(k)) ordered.push(k);
  }

  return ordered.map((key) => {
    const meta = GROUP_META[key];
    return {
      key,
      label: meta ? t(meta.labelKey) : key,
      icon: meta ? meta.icon : "\u2699",
      items: byCategory.get(key) ?? [],
    };
  });
});

/** Flattened item order across groups — drives keyboard navigation and maps a
 *  flat active index back to a (group, item) pair for the `active` class. */
const flatItems = computed<PaletteCommand[]>(() =>
  groups.value.flatMap((g) => g.items),
);

function isActive(cmd: PaletteCommand): boolean {
  return flatItems.value[activeIndex.value]?.id === cmd.id;
}

watch(isOpen, (open) => {
  if (open) {
    activeIndex.value = 0;
    void nextTick(() => {
      inputRef.value?.focus();
    });
  }
});

// Reset active index whenever the result set changes (V1 watch(query)).
watch(
  () => flatItems.value.length,
  (len) => {
    if (activeIndex.value >= len) activeIndex.value = Math.max(0, len - 1);
  },
);

function close(): void {
  hide();
  emit("update:visible", false);
}

function onInput(event: Event): void {
  const value = (event.target as HTMLInputElement).value;
  setQuery(value);
  activeIndex.value = 0;
}

function runCommand(cmd: PaletteCommand): void {
  close();
  void cmd.run();
}

function scrollActiveIntoView(): void {
  void nextTick(() => {
    const el = document.querySelector(".cmd-palette-item.active");
    if (el) el.scrollIntoView({ block: "nearest" });
  });
}

function onKeydown(event: KeyboardEvent): void {
  const len = flatItems.value.length;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    if (len > 0) activeIndex.value = (activeIndex.value + 1) % len;
    scrollActiveIntoView();
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    if (len > 0) activeIndex.value = (activeIndex.value - 1 + len) % len;
    scrollActiveIntoView();
  } else if (event.key === "Enter") {
    event.preventDefault();
    const cmd = flatItems.value[activeIndex.value];
    if (cmd) runCommand(cmd);
  } else if (event.key === "Escape") {
    close();
  }
}

function setActive(cmd: PaletteCommand): void {
  const idx = flatItems.value.findIndex((c) => c.id === cmd.id);
  if (idx >= 0) activeIndex.value = idx;
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="cmd-palette-overlay"
      @click.self="close"
      @keydown="onKeydown"
    >
      <div
        class="cmd-palette"
        role="dialog"
        aria-modal="true"
        :aria-label="t('layout.command_palette_title')"
      >
        <div class="cmd-palette-input-wrap">
          <svg
            class="cmd-palette-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <circle
              cx="11"
              cy="11"
              r="8"
            />
            <line
              x1="21"
              y1="21"
              x2="16.65"
              y2="16.65"
            />
          </svg>
          <input
            ref="inputRef"
            type="text"
            class="cmd-palette-input"
            :placeholder="t('commandPalette.placeholder')"
            :value="store.query"
            @input="onInput"
          />
          <kbd class="cmd-palette-kbd">Esc</kbd>
        </div>

        <div
          v-if="flatItems.length > 0"
          class="cmd-palette-results"
        >
          <div
            v-for="group in groups"
            :key="group.key"
            class="cmd-palette-group"
          >
            <div class="cmd-palette-group-label">
              {{ group.icon }} {{ group.label }}
            </div>
            <div
              v-for="cmd in group.items"
              :key="cmd.id"
              class="cmd-palette-item"
              :class="{ active: isActive(cmd) }"
              @click="runCommand(cmd)"
              @mouseenter="setActive(cmd)"
            >
              <span class="cmd-palette-item-label">{{ cmd.label }}</span>
            </div>
          </div>
        </div>
        <div
          v-else
          class="cmd-palette-empty"
        >
          {{ t('commandPalette.noResults') }}
        </div>
      </div>
    </div>
  </Teleport>
</template>

<!-- No scoped CSS: visuals are owned by global styles/common/utilities.css
     `.cmd-palette*` rules so they stay 1:1 with V1. -->

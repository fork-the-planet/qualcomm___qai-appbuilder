/**
 * `useFontSize` — global font-size preference.
 *
 * S7.5 L7 PR-703 introduced the discrete `sm | md | lg | xl` enum
 * (`ui.fontSize`) + `setFontSize` / `cycle`. Those are retained
 * verbatim for backward compatibility (and the PR-703 shape test).
 *
 * M-align (V1→V2): adds (additive only) the *functional* percentage
 * scale that V1's `useFontSize.js` implemented — it scales the global
 * `--text-*` CSS custom properties on `:root` so every page font
 * resizes uniformly, persists the choice to localStorage, and exposes
 * a slider/step + reset API consumed by the sidebar font-size popover.
 * The enum layer (`fontSize` / `setFontSize` / `cycle`) is left
 * untouched; the percentage layer is what actually moves pixels.
 */
import { computed, ref, watch, type ComputedRef, type Ref } from "vue";

import { useUiStore, type FontSize } from "@/stores/ui";

// ─── Enum layer (PR-703 — unchanged) ─────────────────────────────────────────

const STORAGE_KEY = "qai-font-size";
const SIZE_ORDER: readonly FontSize[] = ["sm", "md", "lg", "xl"];

// ─── Percentage-scale layer (V1 parity — useFontSize.js) ─────────────────────

/** Preset scale steps in percent (V1: every 10% from 50% to 200%). */
const FONT_SIZE_STEPS: readonly number[] = [
  50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200,
];
const DEFAULT_SCALE = 100;
const SCALE_STORAGE_KEY = "qai-font-size-scale";

/** Base sizes (px) — must match styles/variables.css `--text-*` defaults. */
const BASE_SIZES: Readonly<Record<string, number>> = {
  "--text-xs": 11,
  "--text-sm": 12,
  "--text-base": 13,
  "--text-md": 14,
  "--text-lg": 16,
  "--text-xl": 20,
  "--text-2xl": 24,
};

// Module-level singleton scale ref so every `useFontSize()` caller
// shares the same reactive value (a single global font scale).
let _scaleRef: Ref<number> | null = null;
let _scaleWired = false;

/** Apply a percentage scale to the `:root` `--text-*` variables. */
function applyScale(scale: number): void {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  const factor = scale / 100;
  for (const [varName, baseVal] of Object.entries(BASE_SIZES)) {
    root.style.setProperty(varName, `${Math.round(baseVal * factor)}px`);
  }
}

function readStoredScale(): number {
  try {
    const saved = localStorage.getItem(SCALE_STORAGE_KEY);
    const parsed = saved !== null ? parseInt(saved, 10) : NaN;
    return FONT_SIZE_STEPS.includes(parsed) ? parsed : DEFAULT_SCALE;
  } catch {
    return DEFAULT_SCALE;
  }
}

// ─── Composable ──────────────────────────────────────────────────────────────

export function useFontSize() {
  const ui = useUiStore();

  // --- Enum layer (unchanged) ---
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(STORAGE_KEY);
  } catch {
    stored = null;
  }
  if (stored !== null && SIZE_ORDER.includes(stored as FontSize)) {
    ui.setFontSize(stored as FontSize);
  }

  const fontSize: ComputedRef<FontSize> = computed(() => ui.fontSize);

  watch(
    () => ui.fontSize,
    (val) => {
      try {
        localStorage.setItem(STORAGE_KEY, val);
      } catch {
        /* storage unavailable */
      }
    },
  );

  function setFontSize(size: FontSize): void {
    ui.setFontSize(size);
  }

  function cycle(): void {
    const idx = SIZE_ORDER.indexOf(ui.fontSize);
    const next = SIZE_ORDER[(idx + 1) % SIZE_ORDER.length]!;
    ui.setFontSize(next);
  }

  // --- Percentage-scale layer (V1 parity, functional) ---
  if (_scaleRef === null) {
    _scaleRef = ref<number>(readStoredScale());
  }
  const fontSizeScale = _scaleRef;

  if (!_scaleWired) {
    _scaleWired = true;
    // Apply immediately so the page reflects the stored preference, then
    // keep CSS + localStorage in sync on every change.
    applyScale(fontSizeScale.value);
    watch(fontSizeScale, (val) => {
      try {
        localStorage.setItem(SCALE_STORAGE_KEY, String(val));
      } catch {
        /* storage unavailable */
      }
      applyScale(val);
    });
  }

  const currentStepIndex = computed(() =>
    FONT_SIZE_STEPS.indexOf(fontSizeScale.value),
  );
  const canIncrease = computed(
    () => currentStepIndex.value < FONT_SIZE_STEPS.length - 1,
  );
  const canDecrease = computed(() => currentStepIndex.value > 0);
  const fontSizeLabel = computed(() => `${fontSizeScale.value}%`);
  /** 0–100 fill percent for the slider track. */
  const fontSizePercent = computed(() => {
    const max = FONT_SIZE_STEPS.length - 1;
    if (max <= 0) return 0;
    const idx = currentStepIndex.value < 0 ? 0 : currentStepIndex.value;
    return Math.round((idx / max) * 100);
  });

  function increaseFontSize(): void {
    if (canIncrease.value) {
      const next = FONT_SIZE_STEPS[currentStepIndex.value + 1];
      if (next !== undefined) fontSizeScale.value = next;
    }
  }

  function decreaseFontSize(): void {
    if (canDecrease.value) {
      const prev = FONT_SIZE_STEPS[currentStepIndex.value - 1];
      if (prev !== undefined) fontSizeScale.value = prev;
    }
  }

  function resetFontSize(): void {
    fontSizeScale.value = DEFAULT_SCALE;
  }

  return {
    // Enum layer (PR-703 — keep shape stable)
    fontSize,
    setFontSize,
    cycle,
    // Percentage-scale layer (V1 parity)
    fontSizeScale,
    fontSizeLabel,
    fontSizePercent,
    canIncrease,
    canDecrease,
    increaseFontSize,
    decreaseFontSize,
    resetFontSize,
    FONT_SIZE_STEPS,
  };
}

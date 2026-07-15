/**
 * UI-global state store.
 *
 * S5 PR-050: holds locale + theme + sidebar collapsed flag.
 * S5 PR-052: adds (additive only — no field renames or removals)
 *            `documentTitleSuffix`, `resolvedTheme` action helpers, and
 *            `setSidebarCollapsed` for symmetry.
 * S5 PR-053: adds (additive only) global UI state migrated out of
 *            legacy frontend/js/app.js (refactor-plan §8.9):
 *              - `fontSize`        — current font-size mode
 *              - `activeToolMode`  — chat-input tool selector mode
 *              - `showToolMessages` — collapse/expand tool messages
 *              - `globalLoading`   — full-screen busy flag
 * M-align (V1→V2): adds (additive only) chat message-collapse state
 *            consumed by ChatMessageList (V1 index.html:327-337 全部折叠
 *            + 547-553 per-message collapse):
 *              - `messagesCollapsed`   — global "collapse all" flag set
 *                                        by the AppHeader toggle pill
 *              - `collapsedMessageIds` — per-message override map; an
 *                                        entry wins over the global flag
 *                                        so a single message can be
 *                                        expanded while everything else
 *                                        is collapsed (and vice-versa)
 */
import { defineStore } from "pinia";

export type AppTheme = "light" | "dark" | "auto";
export type ResolvedTheme = "light" | "dark";
export type AppLocale = "en" | "zh-CN" | "zh-TW";
export type FontSize = "sm" | "md" | "lg" | "xl";
export type ToolMode =
  | null
  | "app-builder"
  | "model-build"
  | "ppt"
  | "code"
  | "translate"
  | "pro"
  | "gomaster";

interface UiState {
  theme: AppTheme;
  locale: AppLocale;
  sidebarCollapsed: boolean;
  /** Mobile sidebar open state — used on small screens (≤768px) where the
   *  sidebar is off-screen by default. Toggled by the topbar hamburger button. */
  mobileSidebarOpen: boolean;
  /**
   * Effective theme after resolving "auto" against
   * `prefers-color-scheme`. Updated by `useTheme()` (PR-052) so views
   * can consume a definitive value without re-querying matchMedia.
   */
  resolvedTheme: ResolvedTheme;
  /** Optional suffix appended to `document.title` by the route guard. */
  documentTitleSuffix: string;
  /** Font-size class. Persisted by callers if needed. */
  fontSize: FontSize;
  /** Active "tool mode" pill in the chat input area. */
  activeToolMode: ToolMode;
  /** Whether tool-call messages are visible in the chat list. */
  showToolMessages: boolean;
  /** Global "collapse all" flag — toggled by the AppHeader pill. */
  messagesCollapsed: boolean;
  /** Per-message collapse override; presence of a key overrides the
   *  global `messagesCollapsed` flag for that message id. */
  collapsedMessageIds: Record<string, boolean>;
  /** Global busy flag (e.g., during reboot / re-login). */
  globalLoading: boolean;
}

const DEFAULT_LOCALE: AppLocale = "en";
// V1 parity (app.js:122 `isDark = ref(true)`): the UI ships dark by default.
// V2 previously defaulted to "auto" (follow system), so on a light OS the app
// opened light — a regression from V1's always-dark experience. We default to
// "dark" and persist the user's explicit choice (see detectInitialTheme).
const DEFAULT_THEME: AppTheme = "dark";

/** localStorage key used to persist the user's explicit locale choice
 *  (V1 parity: LanguageSwitcher writes the same key). */
const LOCALE_STORAGE_KEY = "qai_locale";
/** localStorage key for the user's explicit theme choice. Persisted so a
 *  reload / re-open restores it (V1 never persisted theme — this is a
 *  deliberate enhancement so "set it once" sticks across restarts). */
const THEME_STORAGE_KEY = "qai_theme";
/** localStorage key for the sidebar collapsed state. Persisted so a
 *  reload / re-open restores the user's preferred sidebar width. */
const SIDEBAR_COLLAPSED_KEY = "qai_sidebar_collapsed";

function detectInitialSidebarCollapsed(): boolean {
  try {
    const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (stored === "true") return true;
    if (stored === "false") return false;
  } catch {
    // localStorage unavailable — fall through to default.
  }
  return false;
}

function detectInitialTheme(): AppTheme {
  // Explicit user choice persisted to localStorage takes precedence so a
  // reload / re-open restores the selected theme; otherwise default to dark.
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "auto") {
      return stored;
    }
  } catch {
    // localStorage unavailable — fall through to the default.
  }
  return DEFAULT_THEME;
}

function detectInitialLocale(): AppLocale {
  // 1) Explicit user choice persisted to localStorage takes precedence so a
  //    full page reload / direct URL open restores the selected language
  //    (previously this was dropped, causing the UI to fall back to English).
  try {
    const stored = localStorage.getItem(LOCALE_STORAGE_KEY);
    if (stored === "en" || stored === "zh-CN" || stored === "zh-TW") {
      return stored;
    }
  } catch {
    // localStorage unavailable (SSR / privacy mode) — fall through to nav lang.
  }
  // 2) Otherwise fall back to the browser UI language.
  if (typeof navigator === "undefined") {
    return DEFAULT_LOCALE;
  }
  const candidate = navigator.language;
  if (candidate?.startsWith("zh-TW") === true) {
    return "zh-TW";
  }
  if (candidate?.startsWith("zh") === true) {
    return "zh-CN";
  }
  return "en";
}

export const useUiStore = defineStore("ui", {
  state: (): UiState => ({
    theme: detectInitialTheme(),
    locale: detectInitialLocale(),
    sidebarCollapsed: detectInitialSidebarCollapsed(),
    mobileSidebarOpen: false,
    resolvedTheme: "dark",
    documentTitleSuffix: "QAIModelBuilder",
    fontSize: "md",
    activeToolMode: null,
    showToolMessages: true,
    messagesCollapsed: false,
    collapsedMessageIds: {},
    globalLoading: false,
  }),
  actions: {
    setTheme(theme: AppTheme): void {
      this.theme = theme;
      // Persist so the choice survives a reload / re-open (mirrors setLocale).
      try {
        localStorage.setItem(THEME_STORAGE_KEY, theme);
      } catch {
        // localStorage unavailable — keep the in-memory value only.
      }
    },
    setLocale(locale: string): void {
      if (locale === "en" || locale === "zh-CN" || locale === "zh-TW") {
        this.locale = locale;
        // Persist so a reload / direct URL open restores the choice
        // (V1 parity: same localStorage key as LanguageSwitcher).
        try {
          localStorage.setItem(LOCALE_STORAGE_KEY, locale);
        } catch {
          // localStorage unavailable — selection still applies for this session.
        }
      }
    },
    toggleSidebar(): void {
      this.sidebarCollapsed = !this.sidebarCollapsed;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(this.sidebarCollapsed));
      } catch {
        // localStorage unavailable — keep in-memory value only.
      }
      // Close mobile sidebar when toggling the collapsed state on desktop.
      this.mobileSidebarOpen = false;
    },
    setSidebarCollapsed(collapsed: boolean): void {
      this.sidebarCollapsed = collapsed;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
      } catch {
        // localStorage unavailable — keep in-memory value only.
      }
    },
    toggleMobileSidebar(): void {
      this.mobileSidebarOpen = !this.mobileSidebarOpen;
    },
    setMobileSidebarOpen(open: boolean): void {
      this.mobileSidebarOpen = open;
    },
    setResolvedTheme(theme: ResolvedTheme): void {
      this.resolvedTheme = theme;
    },
    setDocumentTitleSuffix(suffix: string): void {
      this.documentTitleSuffix = suffix;
    },
    setFontSize(size: FontSize): void {
      this.fontSize = size;
    },
    setActiveToolMode(mode: ToolMode): void {
      this.activeToolMode = mode;
    },
    setShowToolMessages(visible: boolean): void {
      this.showToolMessages = visible;
    },
    /**
     * Set the global "collapse all / expand all" flag. Clears any
     * per-message overrides so the new global state takes effect for
     * every message uniformly (V1 "全部折叠" resets per-message state).
     */
    setMessagesCollapsed(collapsed: boolean): void {
      this.messagesCollapsed = collapsed;
      this.collapsedMessageIds = {};
    },
    /** Toggle the per-message collapse override for one message id. The
     *  override always wins over the global flag (so a user can expand
     *  one message while "collapse all" is active, and vice-versa). */
    toggleMessageCollapsed(messageId: string): void {
      const current =
        this.collapsedMessageIds[messageId] ?? this.messagesCollapsed;
      this.collapsedMessageIds = {
        ...this.collapsedMessageIds,
        [messageId]: !current,
      };
    },
    /** Resolve the effective collapsed state for a message id. */
    isMessageCollapsed(messageId: string): boolean {
      return this.collapsedMessageIds[messageId] ?? this.messagesCollapsed;
    },
    setGlobalLoading(loading: boolean): void {
      this.globalLoading = loading;
    },
  },
});
